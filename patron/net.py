"""Single outbound client: time, call and credit ceilings, retries, ledger and per-job cache."""
import http.client
import contextlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import store
from .text import digest, now

RETRYABLE = {408, 429, 500, 502, 503, 504}

# Crossref's public pool allows one request at a time. Crustdata allows parallel calls up to a per-minute limit
# (5 for identify, 10 for web on a self-serve key), enforced by waiting for X-RateLimit-Reset on a 429.
SPACING = {"crossref": 0.3}
GATES = {name: threading.Lock() for name in SPACING}


class SourceError(Exception):
    pass


def tls_context():
    context = ssl.create_default_context()
    bundle = Path("/etc/ssl/cert.pem")
    if not context.get_ca_certs() and bundle.exists():
        context.load_verify_locations(bundle)
    return context


class Client:
    def __init__(self, job, cfg):
        self.job, self.cfg = job, cfg
        self.deadline = time.monotonic() + cfg["limits"]["seconds"]
        self.tls = tls_context()
        self.lock = threading.Lock()

    def reserve(self, key, service, op, credits):
        with self.lock:
            used = store.one("select count(*) n, coalesce(sum(credits),0) c from ledger where job=?", self.job)
            if used["n"] >= self.cfg["limits"]["http_calls"]:
                raise SourceError("call ceiling reached")
            if credits and used["c"] + credits > self.cfg["limits"]["credits"] + 1e-9:
                raise SourceError("credit ceiling reached")
            if time.monotonic() >= self.deadline:
                raise SourceError("time ceiling reached")
            return store.run(
                "insert into ledger(job,key,service,op,outcome,credits,at) values(?,?,?,?,?,?,?)",
                self.job, key, service, op, "started", credits, now())

    def request(self, service, op, url, params=None, body=None, headers=None, credits=0.0, timeout=20, parse="json"):
        """Return body and retrieval time. A response is reused only inside the job that fetched it."""
        if params:
            url += "?" + urllib.parse.urlencode(params)
        key = digest([service, url, body])
        cached = store.one("select body, at from responses where job=? and key=?", self.job, key)
        if cached:
            return self.decode(cached["body"], parse), cached["at"]

        if service in os.environ.get("PATRON_FAIL", "").split(","):
            raise SourceError(f"{service}: failure injected for testing")
        if credits and store.one("select 1 from ledger where job=? and key=? and outcome in ('started','unknown')", self.job, key):
            raise SourceError(f"{service}: earlier paid call has an unknown outcome, so it was not repeated")

        data = json.dumps(body).encode() if body is not None else None
        send = {"User-Agent": "patron-research-desk/0.1", **(headers or {})}
        if data:
            send["Content-Type"] = "application/json"

        # A paid call that times out may still have been billed, so only free calls retry on timeouts.
        for attempt in range(3):
            row = self.reserve(key, service, op, credits)
            start = time.monotonic()
            wait = None
            try:
                left = max(1, min(timeout, self.deadline - start))
                req = urllib.request.Request(url, data=data, headers=send)
                with GATES.get(service, contextlib.nullcontext()):
                    try:
                        start = time.monotonic()
                        with urllib.request.urlopen(req, timeout=left, context=self.tls) as res:
                            raw = res.read(12_000_000).decode("utf-8", "replace")
                            used = res.headers.get("X-Credits-Used")
                    finally:
                        time.sleep(SPACING.get(service, 0))
                parsed = self.decode(raw, parse)
                stamp = now()
                tokens = 0
                if service == "ollama":
                    tokens = parsed.get("prompt_eval_count", 0) + parsed.get("eval_count", 0)
                with store.db() as c:
                    c.execute("insert or replace into responses values(?,?,?,?)", (self.job, key, raw, stamp))
                    c.execute("update ledger set outcome='ok', credits=?, tokens=?, ms=? where id=?",
                              (float(used) if used else credits, tokens, int((time.monotonic() - start) * 1000), row))
                return parsed, stamp
            except urllib.error.HTTPError as err:
                store.run("update ledger set outcome='error', credits=0, detail=?, ms=? where id=?",
                          f"HTTP {err.code}", int((time.monotonic() - start) * 1000), row)
                problem = f"{service}: HTTP {err.code}"
                if err.code in RETRYABLE:
                    reset = err.headers.get("X-RateLimit-Reset") or err.headers.get("Retry-After")
                    wait = float(reset) if reset and reset.isdigit() else 1.5 * (attempt + 1)
            except (OSError, ValueError, http.client.HTTPException) as err:
                store.run("update ledger set outcome=?, detail=?, ms=? where id=?",
                          "unknown" if credits else "error", type(err).__name__,
                          int((time.monotonic() - start) * 1000), row)
                problem = f"{service}: {type(err).__name__}"
                if not credits:
                    wait = 1.0 * (attempt + 1)
            if wait is None or attempt == 2 or time.monotonic() + wait >= self.deadline:
                raise SourceError(problem)
            time.sleep(wait)

    @staticmethod
    def decode(raw, parse):
        return json.loads(raw) if parse == "json" else raw
