# Patron: the research sponsorship desk

**[Watch the two-minute demo](https://drive.google.com/file/d/1VqcS6d-Ne6z9C1qIyMOKiM32OPB3fVZq/view?usp=share_link)**

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
| Cost per job | Measured with Crustdata: 6.6 to 9.6 credits, about ₹178 to ₹259 at ₹27 a credit, capped at 14. ₹0 in data without a key |
| Pass mark | Every reason links to its record, with the date where the source gives one; weak evidence produces "cannot verify" or a lead; nothing is sent twice or without approval |

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
   customer's own words, and both are removed before search terms are written, so they cannot steer which lab wins.
   An amount that is ambiguous, a range or not in rupees is left open, with a note asking for one figure.
2. Crossref is searched live. A second pass adopts the field's vocabulary, and a third searches likely lab heads by name.
3. Labs are ranked by code from five counts: on-topic papers, last-authored papers, recent papers, papers naming a
   grant and papers with company co-authors. Weights are in `config.json`. Each count earns diminishing credit, `n / (n + half)`. Citations and prestige are not inputs.
4. Competitor links come from paper records and the live web. Crustdata resolves each competitor to one company,
   searches from the competitor's side and from each lab's side, and reads the most relevant pages. A link is
   **confirmed** only when a paper record states it, or when one sentence passes wording rules and the local model
   agrees. The model can only downgrade: it never creates a link, and with no model no sentence is confirmed.
   A company that cannot be identified is never confirmed. The same pages show where competitors already do research,
   and industry ties the customer did not name.
5. A direct link between the professor and a competitor moves that lab to "ask first". It is never presented as proof
   of wrongdoing.

## Sources and checks

| Source | Used for | Key |
| --- | --- | --- |
| [Crossref REST API](https://api.crossref.org) | Papers, affiliations, ORCID, funders, retractions, co-authorship | None |
| [Crustdata](https://docs.crustdata.com) company identify, web search, web fetch | One company under two names, announced partnerships | Optional, recommended |
| Google News RSS | Headline-only fallback for announcements | None |
| Ollama, Gemma | Search terms, title relevance, company names quoted from the request, and a veto on competitor-link sentences. Never money, scores or the decision | Local |

Each paper shows its record link, exact field, printed passage, publication date, retrieval time and record hash.
Every job has a ledger of calls, outcomes, tokens, time and Crustdata credits.

## Where a person steps in

- A request with no research problem gets one question back.
- A person approves or rejects the exact packet, identified by its hash. The hash covers the document that is sent,
  including the agreement wording, the recipient and the terms. Any change needs a new approval.
- Delivery writes an `.eml` file to `data/outbox`, addressed to a `.invalid` domain. No real person is contacted.

## Hard cases

| Case | What happens |
| --- | --- |
| Same name at two institutes | Kept as two people and flagged |
| ORCID missing on some papers | Joined only by name **and** institution |
| Competitor or budget changes | Same searches, so the same labs are considered |
| Preprint and its published version | Counted as one paper |
| Two labs within three points | "Close call: speak to both", not a false winner |
| Publisher prints no affiliation | Joined only by the same ORCID or a shared co-author, and labelled. A different ORCID is never joined |
| Several companies share the competitor's name, or one merely contains it | Not guessed. Retried with the sector, otherwise "cannot verify" and no confirmed link |
| Tag list or menu naming both parties | Ignored as evidence |
| Lookalike names such as JK Cement and JK Lakshmi Cement | Whole-name match, so they are not mixed |
| Article mentions both parties, or a link that is sought, over, or with someone else | Lead, not a fact |
| Undated link | Shown as possibly historical, and cannot change the chosen lab |
| Turnover, unit costs or tonnage next to the budget | Not read as the budget |
| Retracted paper | Excluded and reported |
| A subject nobody publishes on | "Cannot verify", and names the missing subject |
| Paper index down | Job fails as an outage. It is never reported as "no labs" |
| A competitor or lab web search fails | "Not checked", never "none found" |
| Killed mid-run | Resumes from the last checkpoint |
| Killed after writing the email, before recording it | Still one email |
| Paid call with unknown outcome, including 408 and 5xx | Not repeated |
| Same request twice in a day | Opens the existing job |
| Instructions hidden in a request or title | Cannot set scores, approval or delivery, which are all handled by code |

## How we tested it

- An adversarial audit found defects in budget reading, link wording, company identity, approval and paid retries.
  Each now has a regression test in `tests/test_regressions.py`.
- The link check was scored on 19 sentences it was not tuned on: wording rules alone confirmed 7 false links, rules
  plus the model veto 1. It is a small synthetic set. On 7 real announcement sentences all 7 were confirmed.
- Offline tests with synthetic records cover identity, ranking, money, competitor wording, approval, outages and a
  real `SIGKILL` during delivery.
- Live runs on 22 November 2026: low-clinker cement, sodium-ion batteries, textile dye removal, a vague request, a
  prompt injection, a nonsense subject, and cement again with the model switched off.
- A live server was killed during screening and restarted. The six completed paper searches were not repeated.
- Crustdata was run live on 22 November 2026 for low-clinker cement and sodium-ion batteries. An interrupted job
  resumed without repeating a paid call. Replaying the captured responses recovered four
  publicly announced institute and company partnerships, with no false link among the five competitors and six
  institutes replayed. That is a small sample from one industry.
- Eight variants of company names and budgets across two topics produced one search per topic. Two wordings of the
  battery request produced the same first and second labs.

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
- The link check can still be wrong: it confirmed 1 false link in that 19-sentence test. Read the quote before acting.
- Without a Crustdata key, company identity is not checked and confirmed links rely on the name as printed.
- A lab's reply is not yet recorded by the product. `patron/handoff.py` holds the tested rules, but no command or
  screen calls it.
- The runner needs `fcntl`, so it does not run on native Windows. Use macOS, Linux or WSL.
- A link at institute level may involve a different department or topic. It is a question to ask, not a conflict.
- Rewording the technical problem can change the backup labs, and occasionally the first choice.
- A live run with Crustdata takes about two to three minutes.
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
