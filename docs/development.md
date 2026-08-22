# Development

> **Stable Reference — change this only when the actual setup or team workflow changes.**

## Recommended Workflow

First-time setup from the repository root:

```powershell
.\kbf init
```

`kbf init` prepares the project and installs the normal `kbf` command for later use. After the first initialization, either form can be used to initialize or refresh setup:

```powershell
kbf init
.\kbf init
```

Normal full-product development:

```powershell
kbf start
.\kbf start
```

Both forms are supported. The plain `kbf` command is installed by `init`; the `.\kbf` form runs through the repository-local launcher.

Default local URLs:

```text
Product UI:    http://localhost:3000
Backend API:   http://localhost:8000
API docs:      http://localhost:8000/docs
Backend health:http://localhost:8000/health
```

`kbf start` owns the normal local product flow:

```text
Next.js :3000
→ FastAPI :8000
→ AgentService
→ Google ADK Agent
→ Rental Provider
```

Press `Ctrl+C` once to stop both frontend and backend processes.

If the default ports are occupied, choose another pair:

```powershell
kbf start --frontend-port 3001 --backend-port 8021
```

## Agent-only Development

Use the ADK developer UI when working only on Agent behavior or tools:

```powershell
kbf agent
.\kbf agent
```

Default URL:

```text
http://localhost:8765
```

Equivalent low-level command:

```powershell
uv run adk web . --no-reload --port 8765
```

ADK Web is independent of the product frontend. The normal product backend runs the ADK Agent directly through `AgentService`; `kbf start` does not require port 8765.

## Manual Service Commands

Use these only when you need to debug one service independently.

Backend:

```powershell
uv sync --frozen --extra dev --extra backend
uv run --extra backend uvicorn backend.app.main:app --reload --port 8000
```

`uv` reads `.python-version` and uses Python 3.12, matching the backend Docker
image. Normal local work uses `ADK_SESSION_MODE=memory`. Use the temporary
SQLite configuration in `docs/adk-sessions.md` only when testing a backend
restart with the same conversation.

Frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Frontend connects to the backend through:

```text
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Ownership

```text
frontend/**      → Frontend
backend/**       → API and Agent adapter
rental_agent/**  → ADK Agent and rental logic
```

Work inside the owning area whenever possible. Cross-boundary changes should be limited to intentional shared-contract changes.

## Shared Contract

```text
GET  /health
POST /api/chat
```

- Frontend calls `/api/chat`; it does not call ADK directly.
- Backend stays thin and does not recreate rental decision logic.
- Agent changes stay independent of frontend implementation details.
- Keep secrets in ignored local environment files.
- Do not commit API keys or credentials.
- Avoid unrelated refactors while working on a bounded feature.
- Keep the shared API contract stable whenever possible.

## Verification

Python / Backend / Agent:

```powershell
uv run pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q
```

Frontend:

```powershell
cd frontend
npm run check
```

GitHub Actions runs these baseline checks on pushes and pull requests.

## Documentation Rule

Normal feature work should update code and tests, not rewrite Stable Reference documents.

Use `status.md` for current progress and `roadmap.md` for changing priorities. Update this file only when the actual setup, ownership model, or collaboration workflow intentionally changes.
