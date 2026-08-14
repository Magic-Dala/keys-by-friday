# Keys by Friday

AI rental search built with **Next.js + FastAPI + Google ADK**.

> This README is the stable project entry point. New team members should be able to clone the repo, initialize it, and run the full product from here.

## Quick Start

### 1. Requirements

Install:

- [Git](https://git-scm.com/)
- [uv](https://docs.astral.sh/uv/) for Python
- [Node.js](https://nodejs.org/) 24 recommended

On Windows, uv can be installed with:

```powershell
winget install --id=astral-sh.uv -e
```

### 2. Install the project CLI

From the repository root:

```powershell
uv tool install --editable .
```

This gives you the `kbf` command.

### 3. Initialize once

```powershell
kbf init
```

`kbf init` prepares the full local development environment:

- Python dependencies
- FastAPI backend dependencies
- Frontend npm dependencies
- Gemini API key
- RealtyAPI key
- Backend `.env`
- Frontend `.env.local`

The setup will show where to create the required API keys and prompt for them securely.

### 4. Start the full product

```powershell
kbf start
```

Then open:

- **Product UI:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Backend health:** http://localhost:8000/health

`kbf start` runs both the Next.js frontend and FastAPI backend. The backend runs the Google ADK rental agent internally.

Press `Ctrl+C` once to stop both services.

If a default port is already in use, choose another pair:

```powershell
kbf start --frontend-port 3001 --backend-port 8021
```

## Agent-only Development

If you only need the Google ADK developer UI:

```powershell
kbf agent
```

Open:

- **ADK Web:** http://localhost:8765

This is equivalent to:

```powershell
uv run adk web . --no-reload --port 8765
```

ADK Web is for Agent development and debugging. It is **not** the product frontend.

## How Everything Connects

```text
Product UI
http://localhost:3000
        │
        │ POST /api/chat
        ▼
FastAPI Backend
http://localhost:8000
        │
        ▼
AgentService
        │
        ▼
Google ADK Rental Agent
        │
        ▼
Rental Provider
```

The product baseline is:

```text
Next.js Frontend
→ FastAPI Backend
→ AgentService
→ Google ADK Rental Agent
→ Rental Provider
```

Feature work should extend this flow instead of creating a parallel architecture.

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

Frontend code calls the FastAPI contract and does not import Python or ADK directly. Backend code stays thin and does not duplicate Agent search, ranking, or provider logic.

## Commands

| Command | Purpose |
|---|---|
| `kbf init` | First-time setup for the full project |
| `kbf start` | Start Frontend + Backend + ADK product flow |
| `kbf agent` | Start the ADK developer UI only |

For individual service commands and troubleshooting, see [`docs/development.md`](docs/development.md).

## Development Checks

Before opening a PR, the baseline checks are:

```powershell
uv run pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
```

GitHub Actions runs the same baseline checks on pushes and pull requests.

## Documentation

| Document | Purpose |
|---|---|
| `README.md` | Friendly project entry point and stable direction |
| `docs/architecture.md` | Stable system boundaries |
| `docs/api-contract.md` | Stable Frontend ↔ Backend contract |
| `docs/development.md` | Setup, manual commands, and team workflow |
| `docs/agent.md` | Stable Agent authority and behavior rules |
| `docs/status.md` | **Living:** current implementation status |
| `docs/roadmap.md` | **Living:** priorities and next work |

Stable documents should only change when the actual project direction, architecture, API contract, setup, ownership, or Agent authority changes. Normal feature progress belongs in `status.md` and `roadmap.md`.
