# Keys by Friday

AI rental search built with **Next.js + FastAPI + Google ADK**.

Production uses Firestore for product data and an official persistent ADK
database session service for restart-safe conversational state. See
`docs/firestore.md`, `docs/adk-sessions.md`, and
`docs/comparison-shortlist.md`. Public deployment cost protection is explained
in `docs/rate-limits.md`.

If you just want to run the project, start here.

## Quick Start

### 1. Install the prerequisites

You need:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/)
- [Node.js](https://nodejs.org/) 24 recommended

On Windows, install `uv` with:

```powershell
winget install --id=astral-sh.uv -e
```

### 2. Initialize the project once

From the repository root:

```powershell
.\kbf init
```

The setup does the rest for you:

- installs Python and FastAPI dependencies
- installs frontend npm dependencies
- shows where to create the Gemini and RealtyAPI keys
- asks for the keys securely
- creates the local `.env` files
- installs the normal `kbf` command

API keys:

- Gemini: https://aistudio.google.com/app/apikey
- RealtyAPI: https://www.realtyapi.io/

### 3. Start the app

Use either form:

```powershell
kbf start
```

or:

```powershell
.\kbf start
```

Then open **http://localhost:3000**.

Useful local URLs:

| Service | URL |
|---|---|
| Product UI | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Backend health | http://localhost:8000/health |
| Backend readiness | http://localhost:8000/ready |
| ADK Web | http://localhost:8765 |

Press `Ctrl+C` once to stop the frontend and backend.

## CLI Commands

After the first `init`, both the installed command and repository-local launcher are supported:

| Task | Installed command | Repo-local command |
|---|---|---|
| Initialize / refresh setup | `kbf init` | `.\kbf init` |
| Start the full product | `kbf start` | `.\kbf start` |
| Start ADK Web only | `kbf agent` | `.\kbf agent` |

For a completely fresh clone, use `.\kbf init` first. That command installs the normal `kbf` command for later use.

If `kbf` is not found in the current terminal after initialization, open a new terminal or use the `.\kbf ...` form.

## Agent-only Development

To work directly with the Google ADK developer UI without starting the product frontend:

```powershell
kbf agent
```

or:

```powershell
.\kbf agent
```

Then open **http://localhost:8765**.

This wraps:

```powershell
uv run adk web . --no-reload --port 8765
```

ADK Web is for Agent development and debugging. The normal product does **not** depend on port 8765.

## Custom Ports

If port `3000` or `8000` is already being used:

```powershell
kbf start --frontend-port 3001 --backend-port 8021
```

The repository-local form works too:

```powershell
.\kbf start --frontend-port 3001 --backend-port 8021
```

## How the Product Connects

```text
Browser
  ↓
Next.js Frontend :3000
  ↓  POST /api/chat
FastAPI Backend :8000
  ↓
AgentService
  ├→ Google ADK Rental Agent → Rental Provider
  └→ ADK SessionService → memory locally / PostgreSQL in production
```

The frontend talks only to the FastAPI API. The backend owns the ADK adapter. Rental search, ranking, verification, and provider logic stay in `rental_agent/**`.

## Team Ownership

```text
frontend/**      → Frontend
backend/**       → HTTP API and Agent adapter
rental_agent/**  → ADK Agent and rental decision logic
docs/**          → Shared project references
```

The shared web contract is intentionally small:

```text
GET  /health
POST /api/chat
```

Feature work should extend this baseline instead of creating a parallel architecture.

## Before Opening a PR

Run the same baseline checks used by CI:

```powershell
uv run pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
```

GitHub Actions runs the Python and Frontend checks on pushes and pull requests.

## Documentation

| Document | Purpose |
|---|---|
| `README.md` | Start here: setup, commands, and project overview |
| `docs/architecture.md` | Stable system boundaries |
| `docs/api-contract.md` | Stable Frontend ↔ Backend contract |
| `docs/development.md` | Manual service commands and contributor workflow |
| `docs/deployment.md` | macOS, Docker, and Cloud Run backend deployment |
| `docs/authentication.md` | Firebase identity setup and verification |
| `docs/maps.md` | Google Routes / commute setup and testing |
| `docs/firestore.md` | Firestore repositories, shortlist persistence, and verification |
| `docs/adk-sessions.md` | Persistent ADK sessions, restart behavior, concurrency, and configuration |
| `docs/comparison-shortlist.md` | Canonical listings, comparison, shortlist CRUD, and verification |
| `docs/rate-limits.md` | Anonymous Firebase rate limiting, Firestore counters, and cost boundaries |
| `docs/agent.md` | Stable Agent authority and behavior rules |

Stable documents change only when the actual setup, architecture, API contract, ownership, or Agent authority changes.
