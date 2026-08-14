from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


GEMINI_KEY_URL = "https://aistudio.google.com/app/apikey"
REALTYAPI_KEY_URL = "https://www.realtyapi.io/"
DEFAULT_MODELS = (
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash,"
    "gemini-3.5-flash,gemini-2.5-flash"
)
DEFAULT_FRONTEND_PORT = 3000
DEFAULT_BACKEND_PORT = 8000
DEFAULT_AGENT_PORT = 8765


def _project_root() -> Path:
    root = Path.cwd()
    if (root / "pyproject.toml").exists():
        return root
    raise SystemExit("Run this command from the keys-by-friday project directory.")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _read_secret(prompt: str, existing: str | None = None) -> str:
    suffix = " [Enter to keep existing]" if existing else ""
    value = getpass(f"{prompt}{suffix}: ").strip()
    if value:
        return value
    if existing:
        return existing
    raise SystemExit(f"{prompt} cannot be empty.")


def _require_command(name: str, install_hint: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(f"{name} is required. {install_hint}")
    return executable


def _port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _require_available_port(name: str, port: int) -> None:
    if not _port_is_available(port):
        raise SystemExit(f"{name} port {port} is already in use.")


def _wait_for_url(
    name: str,
    url: str,
    process: subprocess.Popen[bytes],
    timeout_seconds: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"{name} exited during startup with code {exit_code}.")
        try:
            with urlopen(url, timeout=1.0) as response:  # noqa: S310 - local readiness URL
                if response.status < 500:
                    time.sleep(0.1)
                    exit_code = process.poll()
                    if exit_code is not None:
                        raise RuntimeError(
                            f"{name} exited during startup with code {exit_code}."
                        )
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{name} did not become ready within {timeout_seconds:.0f}s.")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


def _start_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    kwargs: dict[str, object] = {"cwd": cwd, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]


def init_command() -> int:
    root = _project_root()
    frontend = root / "frontend"

    print("Keys by Friday setup")
    print("====================")

    uv = _require_command(
        "uv",
        "Install it with: winget install --id=astral-sh.uv -e",
    )
    npm = _require_command(
        "npm",
        "Install Node.js 24 (recommended) from https://nodejs.org/",
    )

    print("[1/5] Preparing Python environment...")
    subprocess.run(
        [uv, "sync", "--frozen", "--extra", "dev", "--extra", "backend"],
        cwd=root,
        check=True,
    )

    print("[2/5] Preparing frontend dependencies...")
    subprocess.run([npm, "ci"], cwd=frontend, check=True)

    env_path = root / ".env"
    existing = _read_env(env_path)

    print("\n[3/5] API keys")
    print(f"Gemini API key: {GEMINI_KEY_URL}")
    print(f"RealtyAPI key:   {REALTYAPI_KEY_URL}")
    print("Create the keys in those pages, then paste them below.")

    google_key = _read_secret(
        "Google / Gemini API key",
        existing.get("GOOGLE_API_KEY") or existing.get("GEMINI_API_KEY"),
    )
    realty_key = _read_secret(
        "RealtyAPI key",
        existing.get("REALTYAPI_API_KEY"),
    )
    models = existing.get("GEMINI_MODELS") or DEFAULT_MODELS

    env_path.write_text(
        "\n".join(
            [
                f"GOOGLE_API_KEY={google_key}",
                "GEMINI_API_KEY=",
                "GOOGLE_GENAI_USE_VERTEXAI=FALSE",
                f"GEMINI_MODELS={models}",
                "LISTING_PROVIDER=realtyapi",
                f"REALTYAPI_API_KEY={realty_key}",
                "AGENT_MODE=adk",
                f"FRONTEND_ORIGIN=http://localhost:{DEFAULT_FRONTEND_PORT}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (frontend / ".env.local").write_text(
        f"NEXT_PUBLIC_BACKEND_URL=http://localhost:{DEFAULT_BACKEND_PORT}\n",
        encoding="utf-8",
    )

    print("\n[4/5] Installing the kbf command...")
    subprocess.run(
        [uv, "tool", "install", "--editable", "."],
        cwd=root,
        check=True,
    )

    print("\n[5/5] Done")
    print("Environment is ready.")
    print("\nInitialize again later if needed:")
    print("  kbf init")
    print("  .\\kbf init")
    print("\nStart the full product:")
    print("  kbf start")
    print("  .\\kbf start")
    print("\nStart the Agent-only UI:")
    print("  kbf agent")
    print("  .\\kbf agent")
    print(f"\nProduct UI:    http://localhost:{DEFAULT_FRONTEND_PORT}")
    print(f"API docs:      http://localhost:{DEFAULT_BACKEND_PORT}/docs")
    print(f"Agent-only UI: http://localhost:{DEFAULT_AGENT_PORT}")
    return 0


def start_command(frontend_port: int, backend_port: int) -> int:
    root = _project_root()
    frontend = root / "frontend"
    uv = _require_command("uv", "Run `kbf init` after installing uv.")
    npm = _require_command("npm", "Run `kbf init` after installing Node.js.")

    if not (root / ".env").exists() or not (frontend / "node_modules").exists():
        raise SystemExit("Project is not initialized. Run `kbf init` first.")

    _require_available_port("Frontend", frontend_port)
    _require_available_port("Backend", backend_port)

    backend_env = os.environ.copy()
    backend_env["FRONTEND_ORIGIN"] = f"http://localhost:{frontend_port}"
    frontend_env = os.environ.copy()
    frontend_env["NEXT_PUBLIC_BACKEND_URL"] = f"http://localhost:{backend_port}"

    backend_process = _start_process(
        [
            uv,
            "run",
            "--extra",
            "backend",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
        ],
        cwd=root,
        env=backend_env,
    )
    frontend_process: subprocess.Popen[bytes] | None = None

    try:
        print("Starting Keys by Friday...")
        _wait_for_url(
            "Backend",
            f"http://127.0.0.1:{backend_port}/health",
            backend_process,
        )

        frontend_process = _start_process(
            [npm, "run", "dev", "--", "--port", str(frontend_port)],
            cwd=frontend,
            env=frontend_env,
        )
        _wait_for_url(
            "Frontend",
            f"http://127.0.0.1:{frontend_port}",
            frontend_process,
        )

        print("\nReady")
        print(f"Product UI: http://localhost:{frontend_port}")
        print(f"API docs:   http://localhost:{backend_port}/docs")
        print("Press Ctrl+C to stop both services.\n")

        while True:
            backend_exit = backend_process.poll()
            frontend_exit = frontend_process.poll()
            if backend_exit is not None:
                raise RuntimeError(f"Backend exited with code {backend_exit}.")
            if frontend_exit is not None:
                raise RuntimeError(f"Frontend exited with code {frontend_exit}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping Keys by Friday...")
        return 0
    except RuntimeError as error:
        print(f"\nStartup failed: {error}", file=sys.stderr)
        return 1
    finally:
        if frontend_process is not None:
            _terminate_process(frontend_process)
        _terminate_process(backend_process)


def agent_command(port: int) -> int:
    root = _project_root()
    uv = _require_command("uv", "Run `kbf init` after installing uv.")
    if not (root / ".env").exists():
        raise SystemExit("Project is not initialized. Run `kbf init` first.")

    _require_available_port("ADK Web", port)
    print(f"Starting Agent-only UI at http://localhost:{port}")
    try:
        return subprocess.call(
            [uv, "run", "adk", "web", ".", "--no-reload", "--port", str(port)],
            cwd=root,
        )
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kbf", description="Keys by Friday CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "init",
        help="Prepare Python, frontend dependencies, and local API keys",
    )

    start_parser = subcommands.add_parser(
        "start",
        help="Start the full product (Frontend + Backend + ADK Agent)",
    )
    start_parser.add_argument(
        "--frontend-port", type=_port_number, default=DEFAULT_FRONTEND_PORT
    )
    start_parser.add_argument(
        "--backend-port", type=_port_number, default=DEFAULT_BACKEND_PORT
    )

    agent_parser = subcommands.add_parser(
        "agent",
        help="Start the ADK developer UI only",
    )
    agent_parser.add_argument("--port", type=_port_number, default=DEFAULT_AGENT_PORT)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        return init_command()
    if args.command == "start":
        return start_command(args.frontend_port, args.backend_port)
    if args.command == "agent":
        return agent_command(args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
