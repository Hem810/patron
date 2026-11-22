# Patron: research sponsorship decision pipeline

**[Watch the two-minute demo](https://drive.google.com/file/d/1VqcS6d-Ne6z9C1qIyMOKiM32OPB3fVZq/view?usp=share_link)** · [Architecture](docs/architecture.md) · ContextCon 05, BITS Pilani (own idea)

Patron maps an unstructured sponsor brief to a ranked, evidence-linked lab selection, a competitor-relationship check
and a content-addressed proposal and agreement. Delivery is gated on approval of that SHA and writes one sandbox email.

It is a fixed-stage, checkpointed pipeline, not an autonomous agent system. A local LLM contributes to retrieval and
classification. Scoring, selection, money, approval and delivery are implemented in code.

## Contents

[Runtime](#runtime) · [Execution model](#execution-model) · [Retrieval](#retrieval-and-attribution) · [Ranking](#ranking) ·
[Relationship verification](#relationship-verification) · [Integrity](#approval-and-delivery-integrity) ·
[Network](#network-policy) · [Persistence](#persistence) · [Interfaces](#interfaces) · [Verification](#verification) ·
[Limitations](#limitations)

## Runtime

- Python ≥ 3.10, standard library only. macOS, Linux or WSL (`fcntl` is required).
- SQLite in WAL mode, `ThreadingHTTPServer` on loopback, vanilla JS and CSS.
- Optional: Ollama with `gemma4:latest`, and a Crustdata API key.

```bash
ollama pull gemma4:latest
cp .env.example .env                       # CRUSTDATA_API_KEY
python3 -m patron serve --port 8787        # http://localhost:8787
python3 -m unittest discover -s tests      # 91 tests
```

| Environment variable | Effect |
| --- | --- |
| `CRUSTDATA_API_KEY` | Enables company identity, live web search and page fetch |
| `PATRON_DATA` | Overrides the state directory (default `data/`) |
| `PATRON_FAIL` | Comma-separated service names for which source failure is injected |

## Execution model

```text
brief -> discover -> screen -> deepen -> rank -> rivals -> packet
  |                                        |                  |
  +-> needs_input                          +-> insufficient   +-> awaiting_approval
                                                                    |-> rejected
                                                                    +-> approved -> sent
job states: queued | running | needs_input | insufficient | awaiting_approval | approved | sent | rejected | failed
```

| Stage | Module | Operation |
| --- | --- | --- |
| `brief` | `intake.py`, `money.py` | Schema-constrained parse. Names must occur in the input. Money is parsed by rules. Names and amounts are redacted before search terms are generated |
| `discover` | `papers.py` | Live Crossref retrieval (up to 4 phrases, 100 rows each), up to 2 expansion phrases, reciprocal rank fusion (`Σ 1/(15 + position)`), then an India affiliation filter |
| `screen` | `papers.py` | Retraction filter, then batched LLM title classification (150 titles, batches of 30) |
| `deepen` | `papers.py` | Author-name follow-up searches (up to 12), affiliation attribution, then screening of up to 270 added titles |
| `rank` | `rank.py`, `identity.py` | Entity grouping, work deduplication, evidence gates and scoring |
| `rivals` | `rivals.py`, `crustdata.py` | Company resolution and relationship checks for 3 labs × up to 3 competitors |
| `packet` | `decide.py`, `packet.py` | Selection, two backups, budget, milestones, agreement and SHA seal |

Each stage output is committed as a JSON checkpoint. A per-job `flock` enforces one writer. At server start, `queued`,
`running` and `approved` jobs resume from the first missing checkpoint. Competitor prefetch runs concurrently with
discovery and is joined before paid calls could overlap. Idempotent submission is keyed on the normalised request and date.

## Retrieval and attribution

| Provider | Interface | Data | Failure behaviour |
| --- | --- | --- | --- |
| Crossref | REST, serialised at 0.3 s spacing | Works, authors, ORCID, affiliations, funders, retractions | A discovery outage is a failure, never "no labs" |
| Crustdata | `POST /company/identify`, `/web/search/live`, `/web/enrich/live` | Company identity, announcements, page text | Incomplete checks are `not_checked` or a lead |
| Google News | RSS | Headline-only fallback | Reported as unchecked |
| Ollama | `/api/chat`, JSON schema, `temperature=0`, `seed=7` | Search language, title relevance, quoted names, link veto | Word matching; no sentence-level link is confirmed |

- Identity key: ORCID, otherwise normalised name plus institution. Never name alone.
- Missing affiliations are joined only by the same ORCID or a shared co-author, and labelled. Conflicting ORCIDs never join.
- A preprint and its published version count as one work.
- Paper evidence carries a record URL, source field, printed value, publication date, retrieval time and SHA-256.

## Ranking

Eligibility is at least 2 on-topic works, at least 1 as last author, and coverage of a required subject. For each feature:

```text
score = Σ weight_i * n_i / (n_i + k_i)
```

| Feature | Definition | Weight | k |
| --- | --- | ---: | ---: |
| `fit` | On-topic works | 35 | 5 |
| `lead` | Last-author works | 25 | 4 |
| `recent` | Works in the last 2 years | 20 | 3 |
| `grants` | Works naming a funder | 10 | 3 |
| `industry` | Works with a company-affiliated author | 10 | 1 |

Sort key: `(-score, -lead, -fit, name, key)`. A margin of 3 points or less is a close call. Citations and prestige are
not inputs. Parameters live in `config.json`.

Selection takes the highest-ranked of the top 3 without a confirmed, person-level, dated competitor link from the
five-year window. If all three have one, the top lab stays. An approver can select another checked lab, which regenerates the packet.

## Relationship verification

1. Resolve each competitor to one company. An unresolved identity caps its evidence at `lead`.
2. Search paper records, and the web from both the competitor and lab sides. Fetch at most 3 pages.
3. Apply whole-name matching and sentence-level relationship rules.
4. Apply the LLM veto to accepted sentences. It can narrow person to institution or downgrade to a lead, never upgrade.

| Status | Semantics |
| --- | --- |
| `link_found` | At least one confirmed paper-record or sentence-level link |
| `lead_only` | A candidate exists, but none is confirmed |
| `none_found` | Required searches completed with a resolved or printed identity and no candidate. Not proof of absence |
| `not_checked` | Coverage or identity was insufficient |

Institution-level and undated links cannot change the selected lab.

## Approval and delivery integrity

- `sha = digest(packet without sha)`, covering the rendered document, agreement, recipient, budget and evidence.
- Approval must supply the current SHA. Stale or altered packets are refused, and delivery rechecks the seal.
- Delivery key = `digest(send, job, sha)`. The `.eml` is written with `fsync` and `os.replace`, so a replay yields one file.
- The recipient is `research-office@sandbox.invalid`. There is no SMTP client, and no real person is contacted.
- The LLM and retrieved text cannot approve or deliver. They affect scores only through screened evidence and its features.

## Network policy

| Control | Value |
| --- | --- |
| Calls per job | 90 |
| Crustdata credits per job | 14 |
| Deadline | 240 s per runner invocation |
| Attempts | Up to 3 |
| Free-call retry | Timeouts, 408, 429, 5xx |
| Paid-call retry | 429 only. An unknown billing outcome is not repeated |
| Cache | Scoped to the job, keyed on service, URL and body |

Measured Crustdata jobs used 6.6 to 9.6 credits (₹178 to ₹259 at an assumed ₹27 a credit) and take about two to three
minutes. The ₹50,000 price per completed search is an assumption. The intended buyer is an R&D head who would otherwise use a technology scout.

## Persistence

| Table | Primary key | Contents |
| --- | --- | --- |
| `jobs` | `id` | Request, idempotency key, state, timestamps |
| `steps` | `(job, name)` | Stage checkpoints. Reselecting a lab replaces the packet |
| `responses` | `(job, key)` | Per-job response cache |
| `ledger` | `id` | Service, operation, outcome, credits, tokens, latency |
| `approvals` | `id` | Packet SHA, decision, approver, time |
| `actions` | `key` | Idempotent delivery records |

## Interfaces

| Method | Path | Body |
| --- | --- | --- |
| `GET` | `/api/jobs` | none |
| `GET` | `/api/jobs/{id}` | none |
| `POST` | `/api/jobs` | `{request, fresh}` |
| `POST` | `/api/jobs/{id}/approve` or `/reject` | `{sha, approver}` |
| `POST` | `/api/jobs/{id}/choose` | `{key}` |
| `POST` | `/api/jobs/{id}/retry` | `{}` |
| `GET` | `/proposal/{id}` | none |

The server binds to `127.0.0.1`, validates Host and Origin, accepts JSON only, caps bodies at 20 KB and sets a CSP.

```bash
python3 -m patron run "We make cement and have Rs 50 lakh to cut clinker using calcined clays. We compete with UltraTech."
python3 -m patron show JOB
python3 -m patron approve JOB --sha PACKET --by "Approver name"
python3 -m patron reject JOB --sha PACKET --by "Approver name"
python3 -m patron retry JOB
python3 -m patron resume
```

## Verification

- 91 tests cover money parsing, identity, ranking, link wording, seals, approval, paid retries, outages and `SIGKILL` during delivery.
- Link classifier, 19 held-out synthetic sentences: 7 false links with rules alone, 1 with the model veto. On 7 real
  announcement sentences, all 7 were confirmed.
- Replay of captured web responses recovered 4 announced partnerships with no false link across 5 competitors and 6
  institutes. This is a small sample from one industry.
- Live runs on 22 November 2026: cement, sodium-ion batteries, textile dye removal, vague input, prompt injection, a
  nonsense subject and model-off mode. Restart tests did not repeat completed paper searches or paid calls.
- Eight company-name and budget variants across two topics produced one search per topic.

## Rejected designs

| Design | Reason |
| --- | --- |
| LLM chooses the professor | Unsourced, stale, not repeatable |
| Citation or prestige ranking | Biased to established labs over current fit |
| OpenAlex as the primary index | Keyless quota of $0.10 a day per shared IP |
| Paper funders as the only competitor signal | At most 2% of sampled papers named a company funder |
| Alumni hiring as a feature | School-level records cannot be attributed to a lab |

## Limitations

- No planner or autonomous agents.
- `handoff.py` is tested but not wired. Lab replies are not recorded, and `sent` is terminal.
- `needs_input` and `insufficient` do not resume with new information. An edit creates a new job.
- Private funding, consulting and unpublished agreements are invisible.
- Crossref affiliations are incomplete. Last authorship is only a proxy for lab leadership.
- Institution normalisation is approximate outside major Indian institutes.
- LLM screening and query wording affect retrieval. Rewording can change backups, and occasionally the first choice.
- Web results vary between runs. The link classifier can produce false positives, so read the cited passage.
- An institution-level link may involve another department or topic.
- Without Crustdata, announcements are headline-only and company identity is not resolved.
- The agreement is a draft for legal review. The 20% overhead is a BITS Pilani planning default.
- Ranking uses public work records. No contact details or protected traits are features.

## Provenance and prework

Built with Claude Code during the event. Runtime dependencies are the Python standard library, Ollama and Google's Gemma model.

This repository was started during the event with a fresh history. The code was written from about 1:25 PM IST on
22 November 2026 in an uncommitted working copy of the team's planning repository,
[BirariAditya/ContextCon](https://github.com/BirariAditya/ContextCon), so the first commit here contains the work up
to that point. That repository holds the planning notes and the ideas we explored earlier. Commit times are unaltered.
