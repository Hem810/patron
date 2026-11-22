"""Offline checks for offer terms, disclosure provenance and simulated lab replies."""
import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

from patron import config, decide, handoff, packet, rivals
from patron.text import digest


def lab(key, name, institution, score):
    counts = {metric: 0 for metric in decide.LABELS}
    counts["fit"] = 4
    return {"key": key, "name": name, "institution": institution, "score": score, "orcid": "fixture",
            "counts": counts, "parts": counts, "papers": [],
            "affiliation": {"url": "https://example.invalid/affiliation",
                            "date": "2026-01-01", "text": institution}}


class Sponsorship(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()
        self.lead = lab("ash", "Asha Rao", "IIT Delhi", 65)
        self.backup = lab("mee", "Meena Iyer", "IIT Madras", 50)
        self.ranked = {"labs": [self.lead, self.backup]}
        self.brief = {"budget_inr": 5_000_000, "problem": "Calcined clay cement", "client": "Cement Co"}
        self.date = f"{date.today().year}-01-01"
        self.source = {"source": "Crustdata web fetch", "field": "page content", "at": self.date,
                       "url": "https://example.invalid/partnership", "date": self.date,
                       "search": None, "text": "IIT Delhi leads a cement testbed in partnership with Acmecrete."}
        links, industry = rivals.web_links(
            [self.source], [{"name": "Acmecrete"}], [self.lead], {"cement"}
        )
        self.findings = {"links": links, "industry": industry, "checks": []}
        self.proposal = self.make_packet()
        self.disclosure = self.proposal["disclosures"][0]

    def make_packet(self, amount=4_900_000):
        decision = decide.decide(self.ranked, self.findings, self.cfg)
        return packet.build(self.brief, self.ranked, self.findings, decision, self.cfg, [], offer_inr=amount)

    def reply(self, **changes):
        return {"packet_sha": self.proposal["sha"], "message_id": "lab-demo-01", "intent": "interested",
                "message": "We can take on the work.", "earliest_start": "2027-01-11",
                "proposed_budget_inr": 4_900_000,
                "disclosure_answers": {self.disclosure["id"]: {"status": "none_declared"}}, **changes}

    def evaluate(self, **changes):
        saved = handoff.validate_reply(self.reply(**changes), self.proposal)
        return handoff.build(self.proposal, {**saved, "source": "simulated"}, {"target": "fixture.eml"})

    def test_offer_and_disclosure_are_bound_to_packet_hash(self):
        self.assertEqual(self.proposal["sha"], digest({k: v for k, v in self.proposal.items() if k != "sha"}))
        other = self.make_packet(4_500_000)
        self.assertNotEqual(other["sha"], self.proposal["sha"])
        self.assertEqual(other["disclosures"], self.proposal["disclosures"])
        self.assertEqual(sum(row["amount"] for row in self.proposal["budget"]["milestones"]), 4_900_000)
        with self.assertRaises(ValueError):
            self.make_packet(5_000_001)
        text = packet.render(self.proposal)
        self.assertIn("₹49,00,000", text)
        self.assertIn(self.disclosure["id"], text)

    def test_institute_link_survives_to_decision_ready_handoff(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "ready_for_sponsor_decision")
        self.assertEqual(result["headroom_inr"], 100_000)
        self.assertEqual(result["reply"]["source"], "simulated")
        self.assertEqual(result["disclosures"][0]["evidence"][0]["url"], self.source["url"])
        self.assertEqual(result["disclosures"][0]["answer"]["status"], "none_declared")

    def test_only_dated_direct_relationship_changes_recommendation(self):
        direct = {**self.findings["links"][0], "scope": "person"}
        self.findings["links"] = [direct]
        change = self.make_packet()
        self.assertEqual(change["lab"]["key"], self.backup["key"])
        self.assertEqual(change["decision"]["selection_evidence"], [direct])
        self.assertIn(self.source["url"], packet.render(change))
        self.findings["links"] = [{**direct, "date": None}]
        self.assertEqual(self.make_packet()["lab"]["key"], self.lead["key"])

    def test_terms_and_unresolved_disclosures_require_sponsor_review(self):
        for changes, expected in [
            ({"proposed_budget_inr": 5_800_000}, "exceeds"),
            ({"proposed_budget_inr": 4_950_000}, "differs"),
            ({"disclosure_answers": {}}, "remains open"),
            ({"disclosure_answers": {self.disclosure["id"]: {"status": "overlap_declared"}}}, "overlap"),
        ]:
            with self.subTest(changes=changes):
                result = self.evaluate(**changes)
                self.assertEqual(result["status"], "sponsor_review_required")
                self.assertIn(expected, " ".join(result["issues"]))
        self.assertEqual(self.evaluate(proposed_budget_inr=5_800_000)["headroom_inr"], -800_000)

    def test_decline_and_clarification_have_different_next_actions(self):
        declined = self.evaluate(intent="declined", message="We lack capacity.")
        self.assertEqual(declined["status"], "declined")
        self.assertEqual(declined["backup"]["key"], self.backup["key"])
        clarification = self.evaluate(intent="clarification", message="What is the test volume?")
        self.assertEqual(clarification["status"], "sponsor_review_required")
        self.assertEqual(clarification["reply"]["message"], "What is the test volume?")

    def test_reply_validation_rejects_bad_correlation_and_terms(self):
        for changes in ({"packet_sha": "stale"}, {"proposed_budget_inr": True},
                        {"earliest_start": "2027-02-29"}, {"disclosure_answers": {"wrong": {}}},
                        {"intent": []}, {"message_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(handoff.InvalidReply):
                handoff.validate_reply(self.reply(**changes), self.proposal)

    def test_legacy_packet_keeps_evidence_and_offer_amount(self):
        old = {key: val for key, val in self.proposal.items() if key not in ("offer", "disclosures")}
        result = handoff.build(old, handoff.validate_reply(self.reply(), old), {"target": "fixture.eml"})
        self.assertEqual(result["offer_inr"], 4_900_000)
        self.assertEqual(result["disclosures"][0]["evidence"][0]["url"], self.source["url"])
        self.assertIn("Draft sponsored research agreement", packet.render(old))

    def test_unresolved_identity_cannot_confirm_a_web_relationship(self):
        client = Mock(cfg=self.cfg)
        brief = {**self.brief, "rivals": ["Acmecrete"], "phrases": ["cement"]}
        names = [{"name": "Acmecrete", "search": "Acmecrete", "identity": "unresolved"}]
        searches = [{"kind": "rival", "key": "Acmecrete"}, {"kind": "lab", "key": self.lead["key"]}]
        with patch.dict(os.environ, {"CRUSTDATA_API_KEY": "fixture"}), \
                patch.object(rivals, "resolve", return_value=(names, [], ["Identity ambiguous."])), \
                patch.object(rivals, "joint_papers", return_value=[]), \
                patch.object(rivals, "web_searches", return_value=(searches, [])), \
                patch.object(rivals, "worth_reading", return_value=[]), \
                patch.object(rivals, "web_documents", return_value=([self.source], [])):
            checks = rivals.check(client, brief, {"papers": []}, {"labs": [self.lead]})
        self.assertEqual(checks["links"][0]["strength"], "lead")
        self.assertEqual(checks["checks"][0]["status"], "lead_only")
        self.assertEqual(checks["checks"][0]["identity"], "unresolved")


if __name__ == "__main__":
    unittest.main()
