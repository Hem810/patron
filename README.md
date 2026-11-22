# Patron: the research sponsorship desk

**A company says what research it needs. Patron decides which professor and lab to fund, shows the evidence, checks
whether a competitor is already there, drafts the proposal and agreement, and sends it once after a person approves.**

ContextCon 05, BITS Pilani. Own idea, adjacent to the Research and markets theme.

## The service

| | |
| --- | --- |
| Who pays today | R&D heads who hire technology scouts or ask around their own network |
| Input | One plain-English request: problem, budget and competitors |
| Finished work | A chosen lab with backups, evidence, competitor check, milestones, budget and draft agreement, delivered after approval |
| Price | ₹50,000 per completed search. This is our assumption; we found no published per-search price |
| Cost per job | Measured with Crustdata: 6.6 to 8.6 credits, about ₹178 to ₹232 at ₹27 a credit, capped at 14. ₹0 in data without a key |
| Pass mark | Every reason traces to a dated record, weak evidence produces "cannot verify", and nothing is sent twice or without approval |

## Run it

Python 3.10 or later on macOS or Linux. There is nothing to install with pip.

```bash
ollama pull gemma4:latest            # recommended; without it, word matching is used
cp .env.example .env                 # optional Crustdata key
python3 -m patron serve              # http://localhost:8787
```

Command line:

```bash
python3 -m patron run "We make cement and have Rs 50 lakh to cut clinker using calcined clays. We compete with UltraTech."
python3 -m patron show JOB
python3 -m patron approve JOB --sha PACKET --by "Approver name"
python3 -m patron resume             # continue anything a crash interrupted
```

Tests: `python3 -m unittest discover -s tests`

## How it works

See the [architecture diagram](docs/architecture.md).

1. A local model turns the request into technical search language. Money and company names must appear in the
   customer's own words.
2. Crossref is searched live. A second pass adopts the field's vocabulary, and a third searches likely lab heads by name.
3. Labs are ranked by code from five counts: on-topic papers, last-authored papers, recent papers, papers naming a
   grant and papers with company co-authors. Weights are in `config.json`. Citations and prestige are not inputs.
4. Competitor links come from paper records and the live web. Crustdata resolves each competitor to one company,
   searches from the competitor's side and from each lab's side, and reads the most relevant pages. A link is
   **confirmed** only when one sentence or record states it. Anything weaker is a **lead**. The same pages show where
   competitors already do research, and industry ties the customer did not name.
5. A direct link between the professor and a competitor moves that lab to "ask first". It is never presented as proof
   of wrongdoing.

## Sources and checks

| Source | Used for | Key |
| --- | --- | --- |
| [Crossref REST API](https://api.crossref.org) | Papers, affiliations, ORCID, funders, retractions, co-authorship | None |
| [Crustdata](https://docs.crustdata.com) company identify, web search, web fetch | One company under two names, announced partnerships | Optional, recommended |
| Google News RSS | Headline-only fallback for announcements | None |
| Ollama, Gemma | Search terms and title relevance. Never facts, scores, money or the decision | Local |

Each paper shows its record link, exact field, printed passage, publication date, retrieval time and record hash.
Every job has a ledger of calls, outcomes, tokens, time and Crustdata credits.

## Where a person steps in

- A request with no research problem gets one question back.
- A person approves or rejects the exact packet, identified by its hash. Changing the lab changes the hash.
- Delivery writes an `.eml` file to `data/outbox`, addressed to a `.invalid` domain. No real person is contacted.

## Hard cases

| Case | What happens |
| --- | --- |
| Same name at two institutes | Kept as two people and flagged |
| ORCID missing on some papers | Joined only by name **and** institution |
| Publisher prints no affiliation | Joined only by the same ORCID or a shared co-author, and labelled |
| Several companies with the competitor's name at full confidence | Not guessed. Retried with the sector, otherwise "cannot verify" |
| Tag list or menu naming both parties | Ignored as evidence |
| Lookalike names such as JK Cement and JK Lakshmi Cement | Whole-name match, so they are not mixed |
| Article mentions both parties without stating a link | Lead, not a fact |
| Retracted paper | Excluded and reported |
| A subject nobody publishes on | "Cannot verify", and names the missing subject |
| Paper index down | Job fails as an outage. It is never reported as "no labs" |
| Announcement search down | "Not checked", never "none found" |
| Killed mid-run | Resumes from the last checkpoint |
| Killed after writing the email, before recording it | Still one email |
| Paid call with unknown outcome | Not repeated |
| Same request twice in a day | Opens the existing job |
| Instructions hidden in a request or title | Cannot set scores, approval or delivery, which are all handled by code |

## How we tested it

- Offline tests with synthetic records cover identity, ranking, money, competitor wording, approval, outages and a
  real `SIGKILL` during delivery.
- Live runs on 22 November 2026: low-clinker cement, sodium-ion batteries, textile dye removal, a vague request, a
  prompt injection, a nonsense subject, and cement again with the model switched off.
- A live server was killed during screening and restarted. The six completed paper searches were not repeated.
- Crustdata was run live on 22 November 2026 for low-clinker cement. Replaying the captured responses recovered four
  publicly announced institute and company partnerships, with no false link among the five competitors and six
  institutes replayed. That is a small sample from one industry.

## Approaches considered

| Approach | Outcome |
| --- | --- |
| Ask a model which professor to fund | Rejected: unsourced, stale and not repeatable |
| Rank by citations or prestige | Rejected: favours old and famous labs over current fit |
| OpenAlex as the main index | Tested. The keyless budget is $0.10 a day per shared IP, too fragile for a live demo |
| Find competitors through paper funders | Tested. At most 2 in 100 papers named a company funder in the industries sampled, so announcements were added |
| Alumni hiring as a score | Left out: education records name the school, not the lab, so attribution would be guesswork |
| Rules for decisions, model for language | Chosen |

## Known limits

- Private funding, consulting and unannounced agreements are invisible.
- Last authorship is only a proxy for leading a lab, and conventions differ by field.
- Crossref affiliations are incomplete, so good labs can be missed.
- Institution names are normalised for major Indian institutes and approximate for others.
- Without a Crustdata key, announcements are judged on headlines alone.
- Web search results vary between runs, so a lead found once may not appear again. "None found" never means "none exists".
- A link at institute level may involve a different department or topic. It is a question to ask, not a conflict.
- Rewording a request can change the backup labs.
- The agreement is a starting draft and needs a lawyer. The 20% overhead is a planning default from BITS Pilani's policy.
- Researchers are ranked from public work records. No emails, phone numbers or protected traits are used.

## What comes next

Patents and theses, institute-specific overhead and IP rules, milestone verification before each tranche, and
countries beyond India. Each needs source-by-source validation, which did not fit in one day.

Long term, the same desk can run the whole sponsorship: select, contract, verify each milestone and release the money.

## Credits, history and prework

Built with Claude Code during the event. The runtime uses the Python standard library, Ollama and Google's Gemma model.

This repository was started during the event with a fresh history. The code was written from about 1:25 PM IST on
22 November 2026 in an uncommitted working copy of the team's planning repository,
[BirariAditya/ContextCon](https://github.com/BirariAditya/ContextCon), so the first commit here contains the work up
to that point. That repository holds the planning notes and the ideas we explored earlier. Commit times are unaltered.
