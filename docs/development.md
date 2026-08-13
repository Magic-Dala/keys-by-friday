# Development

> **Stable Reference — keep the workflow simple and change this only when the team workflow changes.**

## Ownership

```text
frontend/**      → Frontend
backend/**       → API and Agent adapter
rental_agent/**  → ADK Agent and rental logic
```

Work inside the owning area whenever possible. Cross-boundary changes should be limited to intentional shared-contract changes.

## Local Development

Backend:

```powershell
uv sync --extra dev --extra backend
uv run uvicorn backend.app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Default local URLs:

```text
Frontend: http://localhost:3000
Backend:  http://localhost:8000
```

Agent-only development may continue through the existing Google ADK runtime.

## Team Rules

- Frontend calls `/api/chat`; it does not call ADK directly.
- Backend stays thin and does not recreate rental decision logic.
- Agent changes stay independent of frontend implementation details.
- Keep secrets in ignored local environment files.
- Do not commit API keys or credentials.
- Avoid unrelated refactors while working on a bounded feature.
- Keep the shared API contract stable whenever possible.

## Documentation Rule

Normal feature work should update code and tests, not rewrite Stable Reference documents.

Use `status.md` for current progress and `roadmap.md` for changing priorities.

Update this file only when the actual setup, ownership model, or collaboration workflow intentionally changes.
