# Keys by Friday — AI Rental Search Agent

> **Stable Reference — keep this document frozen unless the project direction or system boundary changes.**

Keys by Friday is an AI rental-search MVP that turns a natural-language request into verified, explainable rental recommendations.

## Final Direction

```text
Next.js Frontend
→ FastAPI Backend
→ AgentService
→ Google ADK Rental Agent
→ Rental Provider
```

This is the project baseline. Feature work should extend this flow instead of introducing a parallel architecture.

## Ownership

```text
frontend/**      → Frontend
backend/**       → HTTP API and Agent adapter
rental_agent/**  → ADK Agent and rental decision logic
docs/**          → Shared project references
```

## Shared Contract

```text
GET  /health
POST /api/chat
```

Frontend code must not import Python or Google ADK directly. Backend code must not duplicate Agent search, ranking, or provider logic.

## Documentation

| Document | Purpose |
|---|---|
| `README.md` | Final project direction |
| `docs/architecture.md` | Stable system boundaries |
| `docs/api-contract.md` | Stable Frontend ↔ Backend contract |
| `docs/development.md` | Stable team workflow and local setup |
| `docs/agent.md` | Stable Agent rules |
| `docs/status.md` | **Living:** current implementation status |
| `docs/roadmap.md` | **Living:** priorities and next work |

## Documentation Rule

Do not update Stable Reference documents for normal feature work, bug fixes, branch changes, test-count changes, or temporary implementation details.

Only `status.md` and `roadmap.md` are expected to change frequently.

Stable Reference documents should change only when the team intentionally changes the project direction, architecture, API contract, ownership boundary, workflow, or Agent authority rules.
