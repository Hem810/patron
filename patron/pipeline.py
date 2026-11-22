"""Durable job runner. Every stage is checkpointed, so a killed process continues where it stopped."""
import fcntl
import threading
import uuid
from contextlib import contextmanager
from datetime import date

from . import config, crustdata, decide, deliver, intake, packet, papers, rank, rivals, store
from .net import Client, SourceError
from .text import clean, digest, fold, now

STAGES = ["brief", "discover", "screen", "deepen", "rank", "rivals", "packet"]
LIMITS = [
    "Private funding, consulting and unpublished agreements are invisible to public records.",
    "The professor's capacity and willingness are unknown until the institute replies.",
    "Last authorship is a proxy for leading a lab. It is not proof.",
    "Publishers do not always supply affiliations or funders, so some labs and grants are missing.",
]


class Refused(Exception):
    pass


def submit(text, fresh=False):
    text = clean(text)[:4000]
    if not text:
        raise Refused("Describe the research you want to fund.")
    key = digest([fold(text), date.today().isoformat()])
    with store.db() as c:
        c.execute("begin immediate")
        old = c.execute("select id from jobs where request_key=? and status not in ('rejected','failed') "
                        "order by created desc", (key,)).fetchone()
        if old and not fresh:
            return old["id"], True
        job = uuid.uuid4().hex[:12]
        c.execute("insert into jobs values(?,?,?,?,?,?,?)", (job, key, text, "queued", "", now(), now()))
    return job, False


@contextmanager
def locked(job):
    folder = config.data_dir() / "locks"
    folder.mkdir(exist_ok=True)
    with open(folder / f"{job}.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def checkpoint(job, name, work):
    saved = store.get_step(job, name)
    if saved is None:
        store.set_status(job, "running", name)
        saved = work()
        store.put_step(job, name, saved)
    return saved


def run(job):
    with locked(job) as mine:
        if mine:
            _run(job)


def _run(job):
    row = store.one("select * from jobs where id=?", job)
    if not row or row["status"] in ("sent", "rejected", "needs_input", "insufficient", "awaiting_approval"):
        return
    cfg = config.load()
    early = None
    try:
        if row["status"] == "approved":
            return finish(job, cfg)
        client = Client(job, cfg)
        brief = checkpoint(job, "brief", lambda: intake.parse(client, row["request"]))
        if not brief["clear"]:
            return store.set_status(job, "needs_input", brief["question"])
        if crustdata.enabled() and brief["rivals"] and store.get_step(job, "rivals") is None:
            early = threading.Thread(target=prefetch, args=(client, brief, row["request"]), daemon=True)
            early.start()
        found = checkpoint(job, "discover", lambda: papers.discover(client, brief))
        screened = checkpoint(job, "screen", lambda: papers.screen(client, brief, found))
        deeper = checkpoint(job, "deepen", lambda: papers.deepen(client, brief, found, screened))
        ranked = checkpoint(job, "rank", lambda: rank.rank(
            deeper["papers"], deeper, cfg, essentials=brief["essentials"]))
        if not ranked["labs"]:
            reason = "Cannot verify a suitable lab. No researcher had enough on-topic, lab-leading evidence"
            if ranked["uncovered"]:
                reason += f". Not evidenced: {', '.join(ranked['uncovered'])}"
            return store.set_status(job, "insufficient", reason + ". Nothing was drafted.")
        if early:
            early.join()  # the same paid calls must never be in flight twice
        checkpoint(job, "rivals", lambda: rivals.check(client, brief, {**deeper, "phrases": found["phrases"]}, ranked, row["request"]))
        checkpoint(job, "packet", lambda: make_packet(job, cfg))
        store.set_status(job, "awaiting_approval", "")
    except SourceError as err:
        store.set_status(job, "failed", str(err))
    except Exception as err:
        store.set_status(job, "failed", f"Stopped safely: {type(err).__name__}: {err}")
    finally:
        if early:
            early.join()


def prefetch(client, brief, request):
    try:
        rivals.prefetch(client, brief, request)
    except (SourceError, KeyError, TypeError, ValueError):
        pass  # the competitor stage repeats the check and reports what it could not verify


def make_packet(job, cfg, chosen=None):
    step = {name: store.get_step(job, name) for name in STAGES[:-1]}
    decision = decide.decide(step["rank"], step["rivals"], cfg, chosen)
    notes = [n for name in ("brief", "discover", "screen", "deepen", "rivals") for n in step[name]["notes"]]
    for check in step["rivals"]["checks"]:
        if check["lab"] != decision["pick"]:
            continue
        if check["status"] == "none_found":
            notes.append(f"No public link to {check['rival']} was found in paper records and "
                         f"{step['rivals']['web_source']}. A private link may still exist.")
        elif check["status"] == "lead_only":
            notes.append(f"A possible link to {check['rival']} could not be confirmed from a single passage.")
    if step["deepen"]["retracted"]:
        notes.append(f"{len(step['deepen']['retracted'])} retracted paper(s) were excluded.")
    unknowns = list(dict.fromkeys(notes + LIMITS))
    return packet.build(step["brief"], step["rank"], step["rivals"], decision, cfg, unknowns)


def finish(job, cfg):
    current = store.get_step(job, "packet")
    approval = store.one("select * from approvals where job=? and decision='approve' order by id desc", job)
    if not approval or approval["packet_sha"] != current["sha"]:
        return store.set_status(job, "awaiting_approval", "The packet changed, so it needs a new approval.")
    deliver.send(job, current, approval, cfg)
    store.set_status(job, "sent", "Written once to the sandbox outbox. No real person was contacted.")


def review(job, decision, sha, approver):
    approver = clean(approver)[:80]
    if not approver:
        raise Refused("Enter the name of the person deciding.")
    with store.db() as c:
        c.execute("begin immediate")
        row = c.execute("select status from jobs where id=?", (job,)).fetchone()
        saved = c.execute("select output from steps where job=? and name='packet'", (job,)).fetchone()
        if not row or not saved or row["status"] != "awaiting_approval":
            raise Refused("This job is not waiting for a decision.")
        if f'"sha": "{sha}"' not in saved["output"]:
            raise Refused("The packet changed. Read it again before deciding.")
        c.execute("insert into approvals(job,packet_sha,decision,approver,at) values(?,?,?,?,?)",
                  (job, sha, decision, approver, now()))
        c.execute("update jobs set status=?, message='', updated=? where id=?",
                  ("approved" if decision == "approve" else "rejected", now(), job))


def choose(job, key):
    with locked(job) as mine:
        row = store.one("select status from jobs where id=?", job)
        if not mine or not row or row["status"] != "awaiting_approval":
            raise Refused("A lab can only be changed before approval.")
        cfg = config.load()
        labs = store.get_step(job, "rank")["labs"][: cfg["rivals"]["labs_checked"]]
        if key not in [lab["key"] for lab in labs]:
            raise Refused("That lab was not checked for this job.")
        store.put_step(job, "packet", make_packet(job, cfg, key))


def retry(job):
    with locked(job) as mine:
        row = store.one("select status from jobs where id=?", job)
        if not mine or not row or row["status"] != "failed":
            raise Refused("Only a failed job can be retried.")
        store.set_status(job, "queued")


def unfinished():
    return [r["id"] for r in store.every("select id from jobs where status in ('queued','running','approved')")]


def view(job):
    row = store.one("select * from jobs where id=?", job)
    if not row:
        return None
    cfg = config.load()
    step = {name: store.get_step(job, name) for name in STAGES}
    done = [s for s in STAGES if step[s] is not None]
    ledger = store.every("select service,op,outcome,credits,tokens,ms,detail,at from ledger where job=? order by id", job)
    credits = round(sum(x["credits"] for x in ledger), 2)
    found, deeper = step["discover"], step["deepen"]
    return {
        "job": row, "stages": STAGES, "done": done, "brief": step["brief"], "rank": step["rank"],
        "rivals": step["rivals"], "packet": step["packet"],
        "counts": {
            "searched": found and found["searched"], "screened": step["screen"] and step["screen"]["screened"],
            "relevant": deeper and len(deeper["relevant"]), "since": found and found["since"],
            "phrases": found and found["phrases"],
        },
        "ledger": ledger,
        "cost": {"credits": credits, "inr": round(credits * cfg["pricing"]["inr_per_credit"], 2),
                 "calls": len(ledger), "tokens": sum(x["tokens"] for x in ledger),
                 "price": cfg["pricing"]["price_per_job_inr"], "limits": cfg["limits"]},
        "approvals": store.every("select decision,approver,at from approvals where job=? order by id", job),
        "actions": store.every("select kind,target,at from actions where job=?", job),
    }
