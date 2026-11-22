"""Offline tests. All people, papers and companies here are synthetic."""
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

from patron import config, crustdata, decide, deliver, identity, intake, packet, papers, pipeline, rank, rivals, store
from patron.net import Client, SourceError

IITD = "Department of Civil Engineering, Indian Institute of Technology Delhi, New Delhi, India"
IITM = "Department of Civil Engineering, IIT Madras, Chennai, India"


def paper(n, lead=("Asha", "Rao", IITD), title="Calcined clay cement", orcid=None, when="2026-03", **extra):
    given, family, place = lead
    return {"id": f"P{n}", "doi": f"10.0/{n}", "title": f"{title} {n}", "date": when,
            "url": f"https://doi.org/10.0/{n}", "record_url": f"https://api.crossref.org/works/10.0/{n}",
            "authors": [{"given": "Student", "family": f"S{n}", "orcid": None, "affiliations": [place]},
                        {"given": given, "family": family, "orcid": orcid, "affiliations": [place]}],
            "funders": [], "retracted": False, "retrieved_at": "2026-11-22T08:00:00+00:00", "sha256": "x" * 64,
            **extra}


def ranked(papers, essentials=()):
    return rank.rank(papers, {"relevant": [p["id"] for p in papers]}, config.load(), date(2026, 11, 22), essentials)


class Money(unittest.TestCase):
    def test_budget_is_read_from_the_customers_words(self):
        for text, want in (("Rs 50 lakh", 5000000), ("₹1.5 crore", 15000000), ("20 lakhs", 2000000),
                           ("₹5,00,000", 500000)):
            self.assertEqual(intake.budget(text), want)

    def test_numbers_that_are_not_money_are_ignored(self):
        self.assertIsNone(intake.budget("extend life to 5000 cycles with 2 million tests"))

    def test_split_and_milestones_add_up_to_the_budget(self):
        for total in (5000000, 999999, 7):
            out = packet.money(total, config.load()["agreement"])
            self.assertEqual(out["research"] + out["overhead"], total)
            self.assertEqual(sum(m["amount"] for m in out["milestones"]), total)


class Neutral(unittest.TestCase):
    base = "We make batteries and have {m}. Who should we fund to make sodium-ion cells last longer? {c}"

    def neutral(self, money, competitors, names):
        return intake.technical_text(self.base.format(m=money, c=competitors).strip(), names)

    def test_competitors_and_budget_do_not_reach_the_search(self):
        short = self.neutral("\u20b950 lakh", "Our competitors are Acme and Kaveri.", ["Acme", "Kaveri"])
        full = self.neutral("Rs 2 crore", "Our competitors are Acme Industries and Kaveri Energy & Mobility.",
                            ["Acme Industries", "Kaveri Energy & Mobility"])
        none = self.neutral("\u20b950 lakh", "", [])
        self.assertEqual(short, full)
        self.assertEqual(short, none)
        self.assertIn("sodium-ion cells", short)
        self.assertNotIn("Acme", short)

    def test_problem_in_the_same_sentence_survives(self):
        out = intake.technical_text("We compete with Acme and need to cut clinker using calcined clay.", ["Acme"])
        self.assertIn("calcined clay", out)
        self.assertNotIn("Acme", out)

    def test_technical_numbers_are_not_hidden(self):
        self.assertIn("5000 cycles", intake.technical_text("Cells must last 5000 cycles.", []))


class Identity(unittest.TestCase):
    def test_institution_spellings_become_one_record(self):
        for text in (IITD, "Dept. of Civil Engineering, Indian Institute of Technology, Delhi 110016",
                     "IIT Delhi, India"):
            self.assertEqual(identity.institution(text), "IIT Delhi")

    def test_indian_institute_without_the_country_word_counts(self):
        self.assertTrue(identity.in_country("Indian Institute of Technology Delhi"))
        self.assertFalse(identity.in_country("Oregon State University, Corvallis"))

    def test_university_name_is_trimmed(self):
        text = "Department of Chemistry GLA University Mathura Uttar Pradesh India"
        self.assertEqual(identity.institution(text), "GLA University")

    def test_company_is_not_a_lab(self):
        self.assertIsNone(identity.institution("Research Centre, Example Cement Limited, India"))

    def test_namesakes_at_two_institutes_stay_apart(self):
        papers = [paper(1), paper(2), paper(3, ("Asha", "Rao", IITM)), paper(4, ("Asha", "Rao", IITM))]
        labs = ranked(papers)["labs"]
        self.assertEqual(len(labs), 2)
        self.assertIn("Not merged", " ".join(labs[0]["cautions"]))

    def test_record_without_orcid_joins_its_orcid_record(self):
        labs = ranked([paper(1, orcid="0000-0001"), paper(2)])["labs"]
        self.assertEqual([lab["counts"]["fit"] for lab in labs], [2])


class Ranking(unittest.TestCase):
    def test_retracted_paper_is_not_evidence(self):
        self.assertEqual(ranked([paper(1), paper(2, retracted=True)])["labs"], [])

    def test_one_paper_is_not_enough(self):
        self.assertEqual(ranked([paper(1)])["labs"], [])

    def test_missing_subject_stops_the_job(self):
        out = ranked([paper(1), paper(2)], essentials=[["calcined clay"], ["turmeric"]])
        self.assertEqual((out["labs"], out["uncovered"]), ([], ["turmeric"]))

    def test_plural_matches_singular(self):
        self.assertTrue(ranked([paper(1), paper(2)], essentials=[["calcined clays"]])["labs"])

    def test_near_tie_is_called_a_close_call(self):
        labs = ranked([paper(n, orcid="0000-0001") for n in range(21)]
                      + [paper(100 + n, ("Meena", "Iyer", IITM), orcid="0000-0002") for n in range(20)])
        out = decide.decide(labs, {"links": []}, config.load())
        self.assertEqual(out["confidence"], "close call")
        self.assertIn("Speak to both", out["questions"][0])

    def test_preprint_and_published_version_count_once(self):
        published = paper(2)
        preprint = {**paper(3), "title": published["title"].upper(), "doi": "10.2139/ssrn.3"}
        labs = ranked([paper(1), published, preprint])["labs"]
        self.assertEqual(labs[0]["counts"]["fit"], 2)
        self.assertIn("P2", [p["id"] for p in labs[0]["papers"]])

    def test_many_papers_never_tie_with_few(self):
        big = [paper(n) for n in range(29)]
        small = [paper(100 + n, ("Meena", "Iyer", IITM)) for n in range(10)]
        labs = ranked(big + small)["labs"]
        self.assertGreater(labs[0]["score"], labs[1]["score"] + 2)
        why = decide.decide({"labs": labs}, {"links": []}, config.load())["why_not"][labs[1]["key"]]
        self.assertIn("10 against 29", why)

    def test_same_input_gives_same_order(self):
        papers = [paper(1), paper(2), paper(3, ("Meena", "Iyer", IITM)), paper(4, ("Meena", "Iyer", IITM))]
        order = lambda rows: [lab["key"] for lab in ranked(rows)["labs"]]
        self.assertEqual(order(papers), order(papers[::-1]))


class Screening(unittest.TestCase):
    groups = [["calcined clay", "LC3"], ["clinker"]]

    def test_exact_subject_is_kept_by_rule(self):
        self.assertTrue(papers.names_subject("Workability of limestone calcined clays cement", self.groups))

    def test_ambiguous_acronym_is_left_to_screening(self):
        self.assertFalse(papers.names_subject("LC3 lipidation in autophagy", self.groups))

    def test_scattered_words_are_not_the_subject(self):
        self.assertFalse(papers.names_subject("Clay tiles and calcined bauxite", self.groups))


class Unprinted(unittest.TestCase):
    lab = {"name": "Asha Rao", "institution": "IIT Delhi", "orcid": None}

    def bare(self, coauthor):
        out = paper(9)
        out["authors"] = [{"given": coauthor, "family": "Nair", "orcid": None, "affiliations": []},
                          {"given": "Asha", "family": "Rao", "orcid": None, "affiliations": []}]
        return out

    def known(self):
        out = paper(1)
        out["authors"][0].update(given="Kiran", family="Nair")
        return out

    def test_shared_coauthor_joins_and_is_labelled(self):
        got = papers.attribute(self.lab, [self.known()], [self.bare("Kiran")])
        self.assertIn("co-author Kiran Nair", got[0]["authors"][1]["joined"]["basis"])

    def test_name_alone_never_joins(self):
        self.assertEqual(papers.attribute(self.lab, [self.known()], [self.bare("Vikram")]), [])


class Rivals(unittest.TestCase):
    lab = {"key": "k", "name": "Asha Rao", "institution": "IIT Delhi", "orcid": None}

    def strength(self, text, rival):
        return rivals.read_passage(text, self.lab, rival)[0]

    def test_one_sentence_must_state_the_link(self):
        self.assertEqual(self.strength("Acmecrete signs an MoU with IIT Delhi.", "Acmecrete"), "confirmed")
        self.assertIsNone(self.strength("Acmecrete grew. IIT Delhi held a workshop.", "Acmecrete"))

    def test_lookalike_company_is_not_matched(self):
        self.assertIsNone(self.strength("Kaveri Lakshmi Cement partners with IIT Delhi.", "Kaveri Cement"))

    def test_denial_is_not_a_confirmed_link(self):
        self.assertEqual(self.strength("Acmecrete denies any partnership with IIT Delhi.", "Acmecrete"), "lead")

    def test_mention_is_not_a_link(self):
        self.assertEqual(self.strength("Acmecrete staff visited IIT Delhi.", "Acmecrete"), "lead")

    def test_direct_link_moves_the_pick_and_explains_why(self):
        labs = ranked([paper(1), paper(2), paper(3), paper(4, ("Meena", "Iyer", IITM)),
                       paper(5, ("Meena", "Iyer", IITM))])
        link = {"id": "L1", "lab": labs["labs"][0]["key"], "rival": "Acmecrete", "strength": "confirmed",
                "scope": "person", "date": f"{date.today().year}-01-01"}
        out = decide.decide(labs, {"links": [link]}, config.load())
        self.assertEqual(out["pick"], labs["labs"][1]["key"])
        self.assertIn("ask them", out["reasons"][0])


class Crustdata(unittest.TestCase):
    """Response shapes follow the published Crustdata documentation."""

    def client(self, body):
        client = mock.Mock()
        client.request.return_value = (body, "2026-11-22T08:00:00+00:00")
        return client

    def test_one_company_under_two_names_is_checked_once(self):
        body = [{"matched_on": "x", "match_type": "name", "matches": [
            {"confidence_score": 1.0, "company_data": {"crustdata_company_id": 7, "basic_info": {"name": "Example"}}}]}]
        with mock.patch.dict(os.environ, {"CRUSTDATA_API_KEY": "test-only"}):
            names, _, notes = rivals.resolve(self.client(body), {"client": None, "rivals": ["Example", "Example Ltd"]})
        self.assertEqual([n["name"] for n in names], ["Example"])
        self.assertIn("same company", notes[0])

    def test_web_result_becomes_cited_link(self):
        body = {"success": True, "results": [{"source": "web", "title": "Testbeds launched",
                "url": "https://example.org/a", "position": 1,
                "snippet": "IIT Delhi leads a testbed in partnership with Acmecrete."}]}
        names = [{"name": "Acmecrete", "search": "Acmecrete"}]
        with mock.patch.dict(os.environ, {"CRUSTDATA_API_KEY": "test-only"}):
            searches, _ = rivals.web_searches(self.client(body), {"phrases": ["cement"]}, names, [Rivals.lab])
            docs, _ = rivals.web_documents(None, searches, [])
            links, _ = rivals.web_links(docs, names, [Rivals.lab], {"cement"})
        self.assertEqual((links[0]["strength"], links[0]["url"]), ("confirmed", "https://example.org/a"))


class LiveShapes(unittest.TestCase):
    """Traps seen in live Crustdata responses, reduced to synthetic text."""

    def test_namesakes_at_full_confidence_are_not_guessed(self):
        same = [{"id": n, "name": "Acmecrete", "confidence": 1.0} for n in range(3)]
        self.assertIsNone(rivals.best_match("Acmecrete", same))

    def test_exact_name_settles_a_tie(self):
        tie = [{"id": 1, "name": "Example Cement Ltd.", "confidence": 0.8},
               {"id": 2, "name": "Example Cement Depot", "confidence": 0.8}]
        self.assertEqual(rivals.best_match("Example Cement", tie)["id"], 1)

    def test_unrelated_top_match_is_not_accepted(self):
        self.assertIsNone(rivals.best_match("Example Cement", [{"id": 1, "name": "Sample Tech", "confidence": 0.9}]))

    def test_tag_list_is_not_evidence(self):
        tags = "IIT Delhi " + "green cement news tag " * 25 + "Acmecrete testbed"
        self.assertEqual(rivals.read_passage(tags, Rivals.lab, "Acmecrete")[0], None)

    def test_job_title_is_not_a_partnership(self):
        text = "Speakers at IIT Delhi included the Joint President of Acmecrete."
        self.assertEqual(rivals.read_passage(text, Rivals.lab, "Acmecrete")[0], "lead")

    def test_joined_fragments_are_not_one_sentence(self):
        text = "Samplerail signs MoU with IIT Delhi ... Acmecrete Cement Ltd"
        self.assertEqual(rivals.read_passage(text, Rivals.lab, "Acmecrete")[0], None)

    def test_relative_snippet_date(self):
        at = "2026-11-22T10:00:00+00:00"
        self.assertEqual(rivals.snippet_day("2 days ago \u2014 MoU signed", at), "2026-11-20")

    def test_title_does_not_cut_a_quote(self):
        text = "Acmecrete will fund the Dr. Rao Chair at IIT Delhi."
        self.assertEqual(rivals.read_passage(text, Rivals.lab, "Acmecrete")[1], text.rstrip("."))

    def test_menu_does_not_join_a_sentence(self):
        html = "<li>Acmecrete</li><li>Bookmark</li><p>IIT Delhi signed an MoU with Samplerail.</p>"
        self.assertEqual(rivals.read_passage(rivals.page_text(html), Rivals.lab, "Acmecrete")[0], None)

    def test_ambiguous_company_names_the_candidates(self):
        found = ([{"id": 1, "name": "Example Life", "confidence": 0.8},
                  {"id": 2, "name": "Example Industries", "confidence": 0.8}], "t")
        with mock.patch.object(crustdata, "enabled", return_value=True), \
                mock.patch.object(crustdata, "identify", return_value=found):
            _, _, notes = rivals.resolve(None, {"rivals": ["Example"], "problem": "x"})
        self.assertIn("Example Life, Example Industries", notes[0])

    def test_english_snippet_date(self):
        self.assertEqual(rivals.snippet_day("May 14, 2025 \u2014 Testbed"), "2025-05-14")


class Durable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ,
                                   {"PATRON_DATA": self.tmp.name, "PATRON_FAIL": "", "CRUSTDATA_API_KEY": ""})
        self.env.start()
        store.init()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def waiting(self):
        cfg = config.load()
        labs = ranked([paper(1), paper(2)])
        brief = {"client": "Example Ltd", "rivals": [], "problem": "test", "budget_inr": 5000000, "notes": []}
        check = {"links": [], "checks": [], "notes": []}
        built = packet.build(brief, labs, check, decide.decide(labs, check, cfg), cfg, [])
        job, _ = pipeline.submit("synthetic test request")
        store.put_step(job, "packet", built)
        store.set_status(job, "awaiting_approval")
        return job, built

    def sent(self):
        return len(list((config.data_dir() / "outbox").glob("*.eml")))

    def test_repeat_request_opens_the_same_job(self):
        first, _ = pipeline.submit("Fund sodium-ion research")
        self.assertEqual(pipeline.submit("fund  sodium ion RESEARCH"), (first, True))

    def test_nothing_is_sent_without_approval(self):
        job, _ = self.waiting()
        pipeline.run(job)
        self.assertFalse((config.data_dir() / "outbox").exists())

    def test_stale_packet_cannot_be_approved(self):
        job, _ = self.waiting()
        with self.assertRaises(pipeline.Refused):
            pipeline.review(job, "approve", "0" * 64, "Tester")

    def test_second_approval_is_refused(self):
        job, built = self.waiting()
        pipeline.review(job, "approve", built["sha"], "Tester")
        with self.assertRaises(pipeline.Refused):
            pipeline.review(job, "approve", built["sha"], "Tester")

    def test_replay_sends_once(self):
        job, built = self.waiting()
        pipeline.review(job, "approve", built["sha"], "Tester")
        for _ in range(3):
            pipeline.run(job)
            store.set_status(job, "approved")
        self.assertEqual(self.sent(), 1)

    def test_sigkill_after_write_before_record_sends_once(self):
        job, built = self.waiting()
        pipeline.review(job, "approve", built["sha"], "Tester")
        code = ("import os,signal\nfrom patron import pipeline,store\nreal=store.run\n"
                "def die(sql,*a):\n"
                "    if 'into actions' in sql: os.kill(os.getpid(),signal.SIGKILL)\n"
                "    return real(sql,*a)\n"
                f"store.run=die\npipeline.run({job!r})\n")
        died = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT)
        self.assertEqual(died.returncode, -signal.SIGKILL)
        self.assertEqual((self.sent(), store.every("select * from actions")), (1, []))
        self.assertEqual(pipeline.unfinished(), [job])
        pipeline.run(job)
        self.assertEqual((self.sent(), len(store.every("select * from actions"))), (1, 1))
        self.assertEqual(store.one("select status from jobs")["status"], "sent")

    def test_outage_is_a_failure_not_an_empty_answer(self):
        job, _ = pipeline.submit("fund cement research")
        store.put_step(job, "brief", {"clear": True, "phrases": ["cement"], "problem": "cement", "notes": []})
        with mock.patch.dict(os.environ, {"PATRON_FAIL": "crossref,ollama"}):
            pipeline.run(job)
        row = store.one("select status,message from jobs")
        self.assertEqual(row["status"], "failed")
        self.assertIn("outage", row["message"])

    def test_paid_call_with_unknown_outcome_is_not_repeated(self):
        client = Client("j", config.load())
        args = ("crustdata", "web search", "https://example.invalid/x")
        key = __import__("patron.text").text.digest(["crustdata", args[2], {"q": 1}])
        store.run("insert into ledger(job,key,service,op,outcome,credits) values('j',?,'crustdata','x','started',1)", key)
        with self.assertRaisesRegex(SourceError, "not repeated"):
            client.request(*args, body={"q": 1}, credits=1)

    def test_paid_timeout_is_not_repeated(self):
        client, body = Client("k", config.load()), {"q": 2}
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError) as wire:
            for _ in range(2):
                with self.assertRaises(SourceError):
                    client.request("crustdata", "web search", "https://example.invalid/y", body=body, credits=1)
        self.assertEqual(wire.call_count, 1)

    def test_credit_ceiling_stops_paid_calls(self):
        cfg = config.load()
        cfg["limits"]["credits"] = 0.5
        with self.assertRaisesRegex(SourceError, "credit ceiling"):
            Client("j", cfg).request("crustdata", "web search", "https://example.invalid/x", credits=1)

    def test_web_failure_reads_as_not_checked(self):
        lab = {**Rivals.lab}
        brief = {"rivals": ["Acmecrete"], "client": None, "phrases": ["cement"]}
        with mock.patch.object(crustdata, "enabled", return_value=False), \
                mock.patch.dict(os.environ, {"PATRON_FAIL": "news,crossref"}):
            out = rivals.check(Client("j", config.load()), brief, {"papers": []}, {"labs": [lab]})
        self.assertEqual(out["checks"][0]["status"], "not_checked")

    def test_proposal_escapes_hostile_text(self):
        _, built = self.waiting()
        built["lab"]["name"] = "<script>alert(1)</script>"
        out = packet.compose(built)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>", out)


if __name__ == "__main__":
    unittest.main()
