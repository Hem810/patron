"""Local web app. Binds to loopback and refuses cross-site writes."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import packet, pipeline, store

STATIC = Path(__file__).parent / "static"
LOCAL = {"localhost", "127.0.0.1"}


def start(job):
    threading.Thread(target=pipeline.run, args=(job,), daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, kind="application/json"):
        raw = (json.dumps(body, ensure_ascii=False) if kind == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def local(self):
        return (self.headers.get("Host") or "").split(":")[0] in LOCAL

    def do_GET(self):
        if not self.local():
            return self.reply(403, {"error": "local access only"})
        parts = urlparse(self.path).path.strip("/").split("/")
        files = {"": ("index.html", "text/html"), "app.js": ("app.js", "text/javascript"),
                 "app.css": ("app.css", "text/css")}
        if len(parts) == 1 and parts[0] in files:
            name, kind = files[parts[0]]
            return self.reply(200, (STATIC / name).read_text(), kind)
        if parts == ["api", "jobs"]:
            return self.reply(200, store.every(
                "select id,request,status,created from jobs order by created desc limit 20"))
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            found = pipeline.view(parts[2])
            return self.reply(200 if found else 404, found or {"error": "no such job"})
        if len(parts) == 2 and parts[0] == "proposal":
            saved = store.get_step(parts[1], "packet")
            if saved:
                return self.reply(200, packet.render(saved), "text/html")
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if not self.local() or (origin and urlparse(origin).netloc != self.headers.get("Host")):
            return self.reply(403, {"error": "cross-site request refused"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.reply(415, {"error": "JSON only"})
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 <= size <= 20000:
                return self.reply(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(size) or b"{}")
            parts = urlparse(self.path).path.strip("/").split("/")
            if parts == ["api", "jobs"]:
                job, duplicate = pipeline.submit(body.get("request", ""), bool(body.get("fresh")))
                start(job)
                return self.reply(200, {"id": job, "duplicate": duplicate})
            if len(parts) == 4 and parts[:2] == ["api", "jobs"]:
                job, verb = parts[2], parts[3]
                if verb in ("approve", "reject"):
                    pipeline.review(job, verb, str(body.get("sha", "")), body.get("approver", ""))
                    start(job)
                elif verb == "choose":
                    pipeline.choose(job, body.get("key"))
                elif verb == "retry":
                    pipeline.retry(job)
                    start(job)
                else:
                    return self.reply(404, {"error": "unknown action"})
                return self.reply(200, {"ok": True})
            self.reply(404, {"error": "not found"})
        except pipeline.Refused as err:
            self.reply(409, {"error": str(err)})
        except (ValueError, TypeError, AttributeError):
            self.reply(400, {"error": "invalid request"})


def serve(port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    pending = pipeline.unfinished()
    for job in pending:
        start(job)
    print(f"Patron on http://localhost:{port} (resumed {len(pending)} unfinished job(s))", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
