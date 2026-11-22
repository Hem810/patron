"""Sandbox delivery. The idempotency key is the file name, so a replay cannot create a second message."""
import os
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime

from . import config, packet as packets, store
from .text import digest, now


def send(job, packet, approval, cfg):
    key = digest(["send", job, packet["sha"]])
    if store.one("select 1 from actions where key=?", key):
        return key
    box = config.data_dir() / "outbox"
    box.mkdir(exist_ok=True)
    target = box / f"{key[:24]}.eml"
    if not target.exists():
        msg = EmailMessage()
        msg["From"] = "patron@sandbox.invalid"
        msg["To"] = cfg["sandbox_recipient"]
        msg["Subject"] = f"Research sponsorship proposal for {packet['lab']['institution']}"
        msg["Date"] = format_datetime(datetime.fromisoformat(approval["at"]))
        msg["Message-ID"] = f"<{key}@sandbox.invalid>"
        msg.set_content(f"The proposal and draft agreement are attached. Approved by {approval['approver']}.\n")
        msg.add_attachment(packets.render(packet).encode(), maintype="text", subtype="html", filename="proposal.html")
        temp = target.with_suffix(".tmp")
        with open(temp, "wb") as fh:
            fh.write(bytes(msg))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, target)
    store.run("insert or ignore into actions values(?,?,?,?,?)", key, job, "sandbox_email", target.name, now())
    return key
