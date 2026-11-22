"""One test for each defect found by the edge-case audit on 22 November 2026. Synthetic data, no network."""
import email
import os
import tempfile
import threading
import unittest
import urllib.error
from email import policy
from unittest import mock

from patron import config, crustdata, decide, intake, money, net, packet, papers, pipeline, rank, rivals, store
from test_patron import IITD, IITM, Rivals, paper, ranked

LAB = Rivals.lab
AT = "2026-11-22T08:00:00+00:00"


class BudgetReading(unittest.TestCase):
    def test_units_and_spellings(self):
        for text, want in (("Budget ₹50L", 5000000), ("Budget ₹50 L.", 5000000), ("Budget INR 5m", 5000000),
                           ("Budget of fifty lakh rupees", 5000000), ("Budget ₹2cr", 20000000),
                           ("Rs. 50 lakh is available", 5000000), ("Budget Rs50 lakh", 5000000),
                           ("₹50 lakh per year", 5000000), ("Budget: 5000000", 5000000),
                           ("We have 2 crore to fund this", 20000000), ("20 lakhs", 2000000)):
            self.assertEqual(intake.budget(text), want, text)

    def test_other_numbers_are_not_the_budget(self):
        for text in ("We produce 20 lakh tonnes of cement a year. Budget Rs 50 lakh",
                     "Our turnover is ₹500 crore. Research budget is ₹50 lakh",
                     "We are a ₹500 crore company and have ₹50 lakh for research",
                     "It costs Rs 350 per bag. Budget Rs 50 lakh",
                     "We serve 2 crore customers and have ₹50 lakh to fund research",
                     "We want a 500 L reactor. Budget ₹50 lakh"):
            self.assertEqual(intake.budget(text), 5000000, text)
        for text in ("We produce 20 lakh tonnes", "We have 2 crore customers", "Our turnover is ₹500 crore",
                     "We need a 500 L reactor"):
            self.assertIsNone(intake.budget(text), text)

    def test_unclear_amounts_are_not_guessed(self):
        for text in ("Budget ₹50 lakh to ₹1 crore", "Budget ₹50-60 lakh", "Between ₹50 lakh and ₹1 crore",
                     "We can fund ₹30 lakh, possibly ₹40 lakh", "Budget ₹50", "Budget $50,000"):
            amount, note = money.read(text)
            self.assertIsNone(amount, text)
            self.assertTrue(note, text)

    def test_every_money_spelling_is_hidden_from_search(self):
        for amount in ("₹50L", "Rs 2 crore", "fifty lakh rupees", "INR 5m"):
            self.assertIn("[budget]", money.hide(f"Budget {amount}."), amount)
        self.assertIn("20 lakh tonnes", money.hide("We produce 20 lakh tonnes."))


class Links(unittest.TestCase):
    def test_trap_sentences_are_not_confirmed(self):
        for text in ("Samplerail signed an MoU with IIT Delhi, while Acmecrete opened a plant.",
                     "Acmecrete chief, an IIT Delhi alumnus, announced a partnership with Samplerail.",
                     "IIT Delhi partnered with Samplerail to cut emissions at plants like those of Acmecrete.",
                     "Acmecrete plans to seek a partnership with IIT Delhi.",
                     "Acmecrete may fund a lab at IIT Delhi.",
                     "Acmecrete's collaboration with IIT Delhi concluded in 2014.",
                     "IIT Delhi students won the pilot challenge judged by Acmecrete."):
            self.assertNotEqual(rivals.read_passage(text, LAB, "Acmecrete")[0], "confirmed", text)

    def test_month_of_may_is_not_a_hedge(self):
        text = "In May 2025 Acmecrete signed an MoU with IIT Delhi."
        self.assertEqual(rivals.read_passage(text, LAB, "Acmecrete")[0], "confirmed")

    def candidate(self, scope="institution"):
        return rivals.evidence(LAB, "Acmecrete", "confirmed", scope, "web", "https://example.org", "page",
                               "Acmecrete partners with IIT Delhi.", "2026-01-01", AT)

    def test_model_can_veto_but_never_upgrade(self):
        out = rivals.apply_check(self.candidate(), LAB, lambda *a: (False, "planned"))
        self.assertEqual((out["strength"], out["reason"]), ("lead", "planned"))
        lead = {**self.candidate(), "strength": "lead"}
        self.assertEqual(rivals.apply_check(lead, LAB, lambda *a: (True, ""))["strength"], "lead")

    def test_researcher_link_narrows_to_institute(self):
        judge = lambda company, party, passage: (party == "IIT Delhi", "")
        self.assertEqual(rivals.apply_check(self.candidate("person"), LAB, judge)["scope"], "institution")

    def test_no_model_means_not_confirmed(self):
        with mock.patch.object(rivals.llm, "ask", return_value=None):
            out = rivals.apply_check(self.candidate(), LAB, rivals.model_check(None))
        self.assertEqual(out["strength"], "lead")
        self.assertIn("unavailable", out["reason"])

    def test_model_sees_one_spelling_of_each_name(self):
        said = rivals.respelled("IIT Delhi works with Acme-Crete Cement.", "Acme Crete", "IIT Delhi")
        self.assertEqual(said, "IIT Delhi works with Acme Crete.")


class Company(unittest.TestCase):
    def test_containing_the_name_is_not_being_the_company(self):
        found = [{"id": 1, "name": "Example Life Insurance", "confidence": 0.9},
                 {"id": 2, "name": "Example Industries Limited", "confidence": 0.8}]
        self.assertIsNone(rivals.best_match("Example", found))

    def test_failed_lab_search_is_incomplete_coverage(self):
        def search(client, query):
            return (None if query.startswith("IIT Delhi") else []), AT

        one = ([{"id": 1, "name": "Acmecrete", "confidence": 1.0}], AT)
        client = mock.Mock(cfg=config.load())
        with mock.patch.object(crustdata, "enabled", return_value=True), \
                mock.patch.object(crustdata, "identify", return_value=one), \
                mock.patch.object(crustdata, "search", side_effect=search), \
                mock.patch.object(rivals, "joint_papers", return_value=[]), \
                mock.patch.object(rivals, "from_news", return_value=([], [])):
            out = rivals.check(client, {"rivals": ["Acmecrete"], "client": None, "phrases": ["cement"], "problem": "x"},
                               {"papers": []}, {"labs": [LAB]})
        self.assertEqual(out["checks"][0]["status"], "not_checked")
        self.assertTrue(out["notes"])


class Researchers(unittest.TestCase):
    def test_conflicting_orcid_is_never_joined(self):
        lab = {"name": "Asha Rao", "institution": "IIT Delhi", "orcid": "0000-0001"}
        known = paper(1)
        known["authors"][0].update(given="Kiran", family="Nair")
        bare = paper(9)
        bare["authors"] = [{"given": "Kiran", "family": "Nair", "orcid": None, "affiliations": []},
                           {"given": "Asha", "family": "Rao", "orcid": "0000-9999", "affiliations": []}]
        self.assertEqual(papers.attribute(lab, [known], [bare]), [])

    def test_old_and_undated_links_say_so(self):
        labs = ranked([paper(1), paper(2)])
        for day, word in (("2012-01-01", "historical"), (None, "undated")):
            link = {"id": "L", "lab": labs["labs"][0]["key"], "rival": "Acmecrete", "strength": "confirmed",
                    "scope": "institution", "date": day}
            self.assertIn(word, decide.decide(labs, {"links": [link]}, config.load())["questions"][0])


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ,
                                   {"PATRON_DATA": self.tmp.name, "PATRON_FAIL": "", "CRUSTDATA_API_KEY": ""})
        self.env.start()
        store.init()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class PaidCalls(Isolated):
    def send(self, code, credits):
        fail = mock.Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError("u", code, "x", {}, None)))
        with mock.patch("urllib.request.urlopen", fail), mock.patch("time.sleep"):
            for _ in range(2):
                with self.assertRaises(net.SourceError):
                    net.Client("j", config.load()).request(
                        "crustdata" if credits else "crossref", "op", "https://example.invalid/x",
                        body={"code": code, "credits": credits}, credits=credits)
        return fail.call_count

    def test_possibly_billed_failures_are_sent_once(self):
        for code in (408, 500, 502, 503, 504):
            self.assertEqual(self.send(code, 1), 1, code)

    def test_free_calls_still_retry(self):
        self.assertEqual(self.send(502, 0), 6)


class Approval(Isolated):
    def waiting(self):
        cfg = config.load()
        labs = ranked([paper(1), paper(2), paper(3, ("Meena", "Iyer", IITM)), paper(4, ("Meena", "Iyer", IITM))])
        brief = {"clear": True, "client": "Example Ltd", "rivals": [], "problem": "test", "budget_inr": 5000000,
                 "notes": [], "essentials": [], "phrases": ["cement"]}
        check = {"links": [], "checks": [], "notes": [], "web_source": "test"}
        built = packet.build(brief, labs, check, decide.decide(labs, check, cfg), cfg, [])
        job, _ = pipeline.submit("synthetic request")
        for name, value in (("brief", brief), ("discover", {"notes": []}), ("screen", {"notes": []}),
                            ("deepen", {"notes": [], "retracted": []}), ("rank", labs), ("rivals", check),
                            ("packet", built)):
            store.put_step(job, name, value)
        store.set_status(job, "awaiting_approval")
        return job, built

    def message(self):
        files = list((config.data_dir() / "outbox").glob("*.eml"))
        self.assertEqual(len(files), 1)
        return email.message_from_bytes(files[0].read_bytes(), policy=policy.default)

    def test_changes_after_approval_do_not_reach_the_email(self):
        job, built = self.waiting()
        pipeline.review(job, "approve", built["sha"], "Tester")
        changed = config.load()
        changed["sandbox_recipient"] = "someone-else@sandbox.invalid"
        with mock.patch.object(config, "load", return_value=changed), \
                mock.patch.object(packet, "compose", return_value="OWNED BY THE SPONSOR"):
            pipeline.run(job)
        sent = self.message()
        self.assertEqual(sent["To"], built["email"]["to"])
        body = "".join(str(part.get_content()) for part in sent.iter_attachments())
        self.assertIn("jointly owned", body)
        self.assertNotIn("OWNED BY THE SPONSOR", body)
        self.assertIn(built["sha"][:12], body)
        self.assertIn("₹50,00,000", body)
        self.assertEqual(body.strip(), packet.render(built).strip())

    def test_altered_packet_is_not_sent(self):
        job, built = self.waiting()
        pipeline.review(job, "approve", built["sha"], "Tester")
        store.put_step(job, "packet", {**built, "document": "altered"})
        pipeline.run(job)
        self.assertEqual(store.one("select status from jobs")["status"], "awaiting_approval")
        self.assertFalse((config.data_dir() / "outbox").exists())

    def test_approval_during_runner_lock_still_sends(self):
        job, built = self.waiting()

        def approve():
            pipeline.review(job, "approve", built["sha"], "Tester")
            pipeline.run(job)

        worker = threading.Thread(target=approve)
        with pipeline.locked(job):
            worker.start()
            worker.join(0.3)
            self.assertTrue(worker.is_alive())
        worker.join(5)
        self.assertEqual(store.one("select status from jobs")["status"], "sent")

    def test_approval_racing_a_lab_change_is_refused(self):
        job, built = self.waiting()
        real, refused = pipeline.make_packet, []

        def approve():
            try:
                pipeline.review(job, "approve", built["sha"], "Tester")
            except pipeline.Refused as err:
                refused.append(err)

        worker = threading.Thread(target=approve)

        def change(*args):
            worker.start()
            worker.join(0.3)
            return real(*args)

        with mock.patch.object(pipeline, "make_packet", side_effect=change):
            pipeline.choose(job, built["backups"][0]["key"])
        worker.join(5)
        self.assertTrue(refused)
        self.assertEqual(store.one("select status from jobs")["status"], "awaiting_approval")
        self.assertEqual(store.every("select * from approvals"), [])

    def test_retry_waits_for_a_stopping_job(self):
        job, _ = pipeline.submit("retry me")
        store.set_status(job, "failed")
        worker = threading.Thread(target=pipeline.retry, args=(job,))
        with pipeline.locked(job):
            worker.start()
            worker.join(0.2)
        worker.join(5)
        self.assertEqual(store.one("select status from jobs")["status"], "queued")


class Reporting(Isolated):
    def test_insufficient_names_threshold_and_retraction(self):
        job, _ = pipeline.submit("thin evidence")
        steps = (("brief", {"clear": True, "rivals": [], "phrases": ["x"], "essentials": [], "notes": []}),
                 ("discover", {"papers": [], "phrases": ["x"], "notes": []}), ("screen", {"notes": []}),
                 ("deepen", {"papers": [], "notes": [], "retracted": ["P2"]}),
                 ("rank", ranked([paper(1), paper(2, retracted=True)])))
        for name, value in steps:
            store.put_step(job, name, value)
        pipeline.run(job)
        message = store.one("select message from jobs")["message"]
        self.assertIn("at least 2", message)
        self.assertIn("retracted", message)

    def test_currency_and_decimals_make_different_requests(self):
        for first, second in (("Sodium research ₹50 lakh", "Sodium research $50 lakh"),
                              ("Budget ₹1.5 crore", "Budget ₹15 crore")):
            self.assertNotEqual(pipeline.submit(first)[0], pipeline.submit(second)[0])


if __name__ == "__main__":
    unittest.main()
