"""Validate a simulated lab reply and derive the sponsor's next decision."""
import re
from datetime import date

from .packet import disclosure_questions

INTENTS = {"interested", "clarification", "declined"}
ANSWER_STATUSES = {"none_declared", "overlap_declared", "unknown"}
REPLY_FIELDS = {"packet_sha", "message_id", "intent", "message", "proposed_budget_inr",
                "earliest_start", "disclosure_answers"}


class InvalidReply(ValueError):
    pass


def disclosures_for(packet):
    if "disclosures" in packet:
        return packet["disclosures"]
    return disclosure_questions(packet["lab"], packet.get("links", []), packet.get("industry", []))


def validate_reply(payload, packet):
    """Return a normalised payload. The caller supplies receipt metadata after validation."""
    if not isinstance(payload, dict) or payload.keys() - REPLY_FIELDS:
        raise InvalidReply("Expected a lab reply with only the supported fields.")
    sha = payload.get("packet_sha")
    if sha != packet["sha"]:
        raise InvalidReply("The lab reply does not match the delivered packet.")
    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", message_id):
        raise InvalidReply("Supply a stable message ID using letters, numbers, dots, hyphens or underscores.")
    intent, message = payload.get("intent"), payload.get("message")
    if not isinstance(intent, str) or intent not in INTENTS:
        raise InvalidReply("The reply intent must be interested, clarification or declined.")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise InvalidReply("Supply a reply message between 1 and 4,000 characters.")

    quote = payload.get("proposed_budget_inr")
    if quote is not None and (type(quote) is not int or not 0 < quote < 2**63):
        raise InvalidReply("The proposed budget must be a positive integer in rupees.")
    start = payload.get("earliest_start")
    if start is not None:
        try:
            if date.fromisoformat(start).isoformat() != start:
                raise ValueError
        except (TypeError, ValueError):
            raise InvalidReply("The earliest start must be a calendar date in YYYY-MM-DD format.") from None

    answers = payload.get("disclosure_answers", {})
    allowed_ids = {item["id"] for item in disclosures_for(packet)}
    if not isinstance(answers, dict) or answers.keys() - allowed_ids:
        raise InvalidReply("Disclosure answers must reference questions in the delivered packet.")
    normalised_answers = {}
    for key, answer in answers.items():
        if not isinstance(answer, dict) or answer.keys() - {"status", "text"}:
            raise InvalidReply(f"Invalid disclosure answer for {key}.")
        status, explanation = answer.get("status"), answer.get("text", "")
        if not isinstance(status, str) or status not in ANSWER_STATUSES:
            raise InvalidReply(f"Invalid disclosure status for {key}.")
        if not isinstance(explanation, str) or len(explanation) > 2000:
            raise InvalidReply(f"Invalid disclosure explanation for {key}.")
        normalised_answers[key] = {"status": status, "text": explanation.strip()}

    return {"packet_sha": sha, "message_id": message_id, "intent": intent, "message": message.strip(),
            "proposed_budget_inr": quote, "earliest_start": start, "disclosure_answers": normalised_answers}


def build(packet, reply, delivery):
    """Build a reproducible handoff from the delivered packet and its stored reply."""
    offer = packet.get("offer") or {}
    ceiling = offer.get("ceiling_inr", packet["brief"].get("budget_inr"))
    offered = offer.get("amount_inr", packet["budget"]["total"])
    quote = reply["proposed_budget_inr"]
    headroom = ceiling - quote if ceiling is not None and quote is not None else None
    evidence = {item["id"]: item for item in (*packet.get("links", []), *packet.get("industry", []))}
    details = []
    issues = []
    unanswered = []
    for question in disclosures_for(packet):
        answer = reply["disclosure_answers"].get(question["id"])
        sources = [evidence[key] for key in question["evidence_ids"] if key in evidence]
        details.append({**question, "answer": answer, "evidence": sources})
        if not answer or answer["status"] == "unknown":
            unanswered.append(question["id"])
            issues.append(f"Disclosure {question['id']} remains open.")
        elif answer["status"] == "overlap_declared":
            issues.append(f"The lab disclosed overlap in {question['id']}.")
        elif any(item["strength"] == "confirmed" and item["scope"] == "person" for item in sources):
            issues.append(f"Review the lab's answer to {question['id']} alongside the documented direct relationship.")

    if reply["intent"] == "declined":
        status, issues = "declined", []
        next_action = "Review the evaluated backup." if packet["backups"] else "Close this sponsorship attempt."
    elif reply["intent"] == "clarification":
        status = "sponsor_review_required"
        next_action = "Answer the lab's clarification before proceeding."
    else:
        if quote is None or offered is None or ceiling is None:
            issues.append("Confirm the offer, sponsor ceiling and the lab's total quote.")
        elif headroom < 0:
            issues.append("The lab's quote exceeds the sponsor's ceiling.")
        elif quote != offered:
            issues.append("The lab's quote differs from the approved offer.")
        if not reply["earliest_start"]:
            issues.append("Confirm the lab's earliest start date.")
        status = "sponsor_review_required" if issues else "ready_for_sponsor_decision"
        next_action = ("Resolve the flagged terms or disclosures." if issues
                       else "Review the agreed terms before authorising the next sponsorship step.")

    backup = packet["backups"][0] if status == "declined" and packet["backups"] else None
    return {
        "status": status, "next_action": next_action, "issues": issues,
        "lab": {key: packet["lab"][key] for key in ("key", "name", "institution")},
        "backup": {key: backup[key] for key in ("key", "name", "institution")} if backup else None,
        "packet_sha": packet["sha"], "delivery": delivery, "reply": reply,
        "offer_inr": offered, "ceiling_inr": ceiling, "quote_inr": quote, "headroom_inr": headroom,
        "disclosures": details, "unanswered_disclosure_ids": unanswered,
    }
