# Patron implementation plan

Patron replaces the technology scout who finds a research lab, checks its fit and industry ties, prepares an offer, and follows up to find out whether the lab can take on the work. An R&D head supplies a research problem, budget in rupees, and any named competitors. Patron delivers an evidence-backed proposal after approval, records a **simulated lab response**, and gives the sponsor the next decision with the terms and unresolved questions in one place.

This is the proposed sprint for Patron. The current baseline already has checkpointed paper research, deterministic lab ranking, competitor checks, packet approval and a sandbox outbox. The offer and reply features below need implementation and verification. [Existing repository baseline](https://github.com/Hem810/patron/tree/8c0316155ecd14c44bbe5e9137ac0a8219f9a1a9) · [Architecture](docs/architecture.md)

## What the judges should see

Use a ₹50 lakh brief to cut clinker with calcined clay, naming UltraTech as a competitor, with an illustrative ₹49 lakh offer approved by the sponsor. Show why the lab matches the technical brief, the exact Crustdata passage behind a question about overlap, and the proposed terms. The sponsor approves that exact packet and Patron creates one sandbox email. A teammate acting as the lab provides an earliest start, a proposed total, and an answer to the overlap question. Patron links the reply to the sent packet and shows the budget gap or headroom and the sponsor’s next action.

A qualifying reply produces a decision-ready sponsorship handoff. A changed quote, unresolved disclosure, or clarification goes to sponsor review. A decline closes the attempt and shows the next evaluated lab when one is available. Contract signature and funding remain future workflow stages. Label live evidence, replayed evidence, and the simulated reply independently. Record observed wall time, calls, and Crustdata credits.

## Build scope and priorities

| Priority | Deliverable | Acceptance check |
| --- | --- | --- |
| Required | One approved proposal with an offer summary or letter and one simulated lab reply | The CLI shows a persisted handoff after restart. Replaying the send or reply creates one record of each. |
| Required | Crustdata evidence that changes the work | A dated source changes the selection under the existing direct-link rule or adds a specific disclosure question. The demo follows that evidence into the lab’s reply and sponsor handoff. |
| Required | Approval and evidence integrity | Approval is bound to the exact packet. An unapproved or stale packet cannot be delivered. Missing sources, ambiguous identities, leads, and verified links are distinguishable. |
| If the core flow passes | Sponsor-configured funding bands and tiered approval | Show the amount calculation and the policy applied when approving it. An out-of-limit approver cannot send. |
| After the freeze | Configurable stage registry, multi-tenant workers, and live lab communications | Define and migrate versioned contracts, shared provider limits, and the delivery integration before switching production workloads. |

A deterministic offer summary inside the existing proposal is enough for the first integrated run. A separate offer letter is the first presentation enhancement. Finish the reply workflow and its tests before adding funding bands, expanded approval UI, or a configurable stage runner. Use the CLI and the existing UI for all demo operations.

## Contracts for both agents

### Evidence and proposal

- Keep Crossref responsible for papers, affiliations, and retractions. Keep Crustdata Company Identify and Web Search/Fetch responsible for public competitor checks. Use the existing shared client, response cache, limits, and ledger.
- Persist evidence with its source URL, the relevant passage or field, publication date when available, retrieval time, and evidence ID. A public institution-level link raises a question about overlap. A direct, dated researcher link can affect selection under the existing policy. Private agreements remain unknown.
- Add a `disclosures` array to new packets before hashing. Each entry has `id`, `question`, and `evidence_ids`. IDs should be stable for the same lab and relationship. Existing packets can still render with their stored decision questions.
- Add proposed funding, overhead assumptions, term, and milestones to the hashed packet. Keep a plain-text email summary. If the separate letter ships, render `offer_letter.html` alongside the existing `proposal.html`, which contains the draft agreement. Compute the hash from the canonical packet fields. Derive the display reference from that hash when rendering.
- If the approved recipient or terms change, create a new packet and require new approval. Keep the sandbox recipient on an `.invalid` domain.

### Offer and approval

Base the offer on a sponsor-approved amount or package within the sponsor’s stated ceiling. With a missing budget or no eligible amount, request input before preparing a priced offer. Treat the public research rank as evidence of technical fit. Any optional score-to-funding bands must come from explicit sponsor policy and show the formula, assumptions, and reasons. Evidence of weak fit or a competitor tie may require review, a narrower pilot, or a different lab. It does not establish the market price of the research.

Store money as integer rupees. If bands are enabled, a configured percentage and increment must produce an amount at or below the cap, with a residual adjustment so overhead and research sum to the offer and tranches sum exactly to the total. Treat overhead as an estimate pending institutional confirmation. Changing the selected lab or changing terms must rebuild the packet, including the applicable offer and disclosures.

Keep an approver and the approved packet SHA in the existing approval record. If configurable approval limits ship, enforce the listed approver, their rupee cap, packet review window, and a reason on rejection in CLI/service code. Set these from the sponsor’s demo policy. Evaluate age at approval time, and honour a valid recorded approval during delivery recovery. Treat a CLI-entered name as a local demo identity. For the same job, serialize lab selection and approval or make both update the draft under a transactional version check.

### Lab response and handoff

Proposed CLI:

```text
python3 -m patron record-reply JOB --file reply.json
python3 -m patron show JOB
```

The CLI supplies the job ID. Use this sample after substituting the exact packet SHA and disclosure ID from the delivered proposal.

```json
{
  "packet_sha": "<full approved packet SHA>",
  "message_id": "lab-demo-01",
  "intent": "interested",
  "message": "We can take on the proposed scope in January.",
  "proposed_budget_inr": 4900000,
  "earliest_start": "2027-01-11",
  "disclosure_answers": {
    "<disclosure ID>": {
      "status": "none_declared",
      "text": "The published partnership was with another team."
    }
  }
}
```

- Accept `interested`, `clarification`, or `declined`. Capture receipt time in Patron and set the source to `simulated` at the CLI boundary. Validate the packet SHA, message ID, positive integer budget when supplied, ISO date, and disclosure IDs. Treat the message as text.
- Check the sent job, current packet, and matching sandbox delivery record in the same database transaction that inserts the reply. Use an additive `lab_responses` table keyed by `(job, packet_sha)`. An identical replay returns the stored reply. A different reply for that version is refused during this sprint. Preserve the immutable delivered packet and derive reply status separately from delivery status.
- For an interested reply, report the approved offer, sponsor cap, lab quote, and difference. A proposed change to the approved terms, cap breach, missing start date, or unresolved required disclosure goes to `sponsor_review_required`. A fully evidenced response within the approved terms goes to `ready_for_sponsor_decision`. A disclosure answer records what the simulated lab says. Keep the public evidence next to it and flag active overlap or contradictions for review.
- A clarification returns the lab’s specific question and the sponsor’s next action. A decline records the reason and evaluated backup if available. Neither creates a follow-on email or a new financial commitment.

## Tradeoffs at code freeze

Reuse the existing pipeline checkpoints, provider contracts and sandbox idempotency key. Record source errors with enough detail to distinguish partial coverage from an absence of matches. When changing a persisted checkpoint later, version its output and either adapt it or invalidate dependent work. Defer arbitrary stage swapping mid-run. Scale workers and provider quotas after the event using the boundaries in the [architecture](docs/architecture.md).

## Build split and gates

Use 17:40 IST on 22 November 2026 as the team’s planning cutoff from the attached draft. Confirm the official cutoff and use the earlier time if it differs. The gates below are measured back from that team cutoff so they work even if implementation starts late. When time is short, skip optional features and preserve the core acceptance checks.

Both agents branch from the same commit. Each owns the files below, flags interface changes at the next gate, and integrates with the other agent’s reviewed changes. Keep the baseline tests in place.

| Gate | Hem’s agent | Aditya’s agent |
| --- | --- | --- |
| By **F−85** · 16:15 | Confirm baseline suite on a supported runner, delivery action key, and integration points. | Confirm packet, evidence, reply, and handoff schemas. Prepare the example brief and reply. |
| By **F−45** · 16:55 | Own `pipeline.py`, `store.py`, `deliver.py`, and `__main__.py`. Wire the approval, outbox, reply transaction and CLI. Test replay, stale approval and restart. | Own `packet.py`, `decide.py`, `rivals.py`, and new `handoff.py`. Build the offer and disclosure fields, handoff rules, and evidence/reply fixtures. Add opt-in funding or approval policy helpers only if the core passes. |
| By **F−25** · 17:15 | Merge the two branches. Run one clean case through approval, delivery and reply. Verify an existing database still opens. | Cross-review the integration. Run the sponsor-review, decline, and clarification cases. Confirm the evidence IDs in the offer, reply, and handoff all match. |
| By **F−10** · 17:30 | Finish blocker fixes and run the final test gate. Keep a passing commit and a known-good replay. | Verify the evidence, checklist, and actual cost figures. Update the README to match the passing implementation and prepare the demo. |
| **F** · 17:40 | Freeze the passing commit. | Use that commit for judging and the demo. |

Hem owns the integration branch and engine tests. Aditya owns evidence, offer, and handoff tests plus the judging notes. For shared integration changes, agree the signatures first and let the file owner make the edit. Save handoff notes with the relevant commit, test results, interface changes, and any decision the other agent needs to make.

## Fifteen edge cases

These are acceptance checks. Existing tests cover parts of the baseline, and the revised workflow still needs verification. Record the commit, result, and exact test name or fixture for every row. Keep baseline and new checks distinct.

| # | Case | Expected result | Owner |
| --- | --- | --- | --- |
| 1 | Vague research brief or missing rupee ceiling | Ask for the missing input. A priced packet requires a valid budget. | Aditya |
| 2 | Crossref returns records but evidence misses the technical threshold | Report insufficient evidence and name the unmet requirement. Create no proposal. | Aditya |
| 3 | Crossref is unavailable | Report a source outage. Preserve unrelated completed checkpoints. | Hem |
| 4 | Two researchers share a name, with incomplete affiliation or ORCID | Keep identities separate unless attribution rules support a merge. Show uncertainty. | Aditya |
| 5 | A top paper is retracted | Exclude it from scoring and report the exclusion. | Aditya |
| 6 | A competitor name resolves ambiguously or resembles another firm | Flag the unresolved identity and avoid attributing links to a guessed entity. | Aditya |
| 7 | A page mentions both parties without describing a relationship, or a lookup fails | Show a lead or incomplete coverage as applicable. No confirmed link is created. | Aditya |
| 8 | A dated source connects the lead researcher to a named competitor | Surface the exact passage and resulting disclosure or selection change. | Aditya |
| 9 | A paid lookup times out ambiguously or reaches the credit cap | Preserve the ledger, show unavailable evidence, and avoid repeating an ambiguously billed request. | Hem |
| 10 | Selection changes during review, or an approver exceeds a configured limit | Refuse stale approval or the restricted approver. Keep one consistent packet, approval and target. | Hem |
| 11 | The process stops after writing the sandbox email but before recording the action | Resume with one email and one matching action. Verify the hashed offer in the attachment. | Hem |
| 12 | A lab reply arrives early or points to another packet hash | Refuse it and leave reply state unchanged. | Hem |
| 13 | An identical reply is retried concurrently, or the same ID is reused with changed content | Commit the identical reply once. Refuse the changed payload. | Hem |
| 14 | Lab quotes ₹58 lakh against a ₹50 lakh cap, leaves a disclosure unanswered, or declares overlap | Show sponsor review with the ₹8 lakh gap or the outstanding issue. | Aditya |
| 15 | Lab declines or asks for clarification | Record the reason and evaluated backup, or show the exact question and sponsor action. | Aditya |

## Final verification

- Run `python3 -m unittest discover -s tests` on macOS or Linux. Native Windows cannot import the reviewed baseline’s `fcntl`. Use a clean temporary data directory for the full flow and also check additive database changes against existing data.
- Use the normal CLI to run a request through approval, sandbox delivery, and a teammate’s simulated reply. Restart, retrieve the same handoff, and repeat the delivery and reply attempts to verify one recorded delivery and reply per packet.
- Check the final source passages, budget and tranche arithmetic, approval hash, lab response label, ledger, and both agents’ test results. Report measured values and label scenarios that have only been reviewed.
- Rehearse the two-minute demo in this order. Sponsor brief, evidence and offer, approved sandbox send, simulated lab reply, sponsor decision. Keep the fifteen cases available as supporting material.

The attached implementation draft, patch, architecture, and coordination notes supplied design inputs for this revision. [ContextCon dashboard](https://crustdata.com/contextcon/bits-pilani-2026/dashboard#guide) · [Crustdata capabilities](https://docs.crustdata.com/general/capabilities.md)
