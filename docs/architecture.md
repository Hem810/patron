# Architecture

```mermaid
flowchart TD
    C[Customer request] --> I[1. Read request]
    I -->|no research problem| Q[Ask one question]
    I --> D[2. Search papers]
    D --> S[3. Screen relevance]
    S --> P[4. Check each researcher by name]
    P --> R[5. Rank labs]
    R -->|too little evidence| N[Cannot verify: draft nothing]
    R --> V[6. Check competitors]
    V --> K[7. Proposal, milestones, agreement]
    K --> A{Person approves this exact packet}
    A -->|reject| X[Stop: nothing sent]
    A -->|approve| O[Sandbox outbox, exactly once]

    M[Local model via Ollama] -. search terms and relevance only .-> I
    M -.-> D
    M -.-> S
    CR[Crossref REST API] -. papers, affiliations, funders, retractions .-> D
    CR -.-> P
    CR -. co-authorship .-> V
    CD[Crustdata: identify, web search, page fetch] -. competitor and lab searches .-> V
    I -. competitor searches start early .-> CD
    NW[News headlines RSS] -. keyless fallback .-> V

    subgraph Guard[Every outbound call passes through patron/net.py]
      L[Time, call and credit ceilings]
      T[Retries, rate-limit waits, per-job response cache]
      G[(Cost ledger)]
    end
    subgraph State[SQLite]
      J[(Jobs and stage checkpoints)]
      H[(Approvals bound to packet hash)]
      E[(Delivery idempotency keys)]
    end
    D --> Guard
    V --> Guard
    K --> J
    A --> H
    O --> E
```

| Concern | Where |
| --- | --- |
| Request reading, money, names | `patron/intake.py` |
| Paper discovery and screening | `patron/papers.py` |
| Same person or institution, one record | `patron/identity.py` |
| Scoring (no model involved) | `patron/rank.py` |
| Competitor evidence | `patron/rivals.py`, `patron/crustdata.py` |
| Choice and explanation | `patron/decide.py` |
| Proposal and agreement | `patron/packet.py` |
| Limits, retries, ledger | `patron/net.py` |
| Checkpoints, approval, resume | `patron/pipeline.py` |
| Exactly-once delivery | `patron/deliver.py` |

A hundred times the volume: move SQLite to Postgres, run stages from a worker queue, and share one rate limiter per
source. A second client: add a tenant column to every table and give each tenant its own configuration and ceilings.
