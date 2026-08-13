from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path
import shutil
import subprocess
import sys


GEMINI_KEY_URL = "https://aistudio.google.com/app/apikey"
REALTYAPI_KEY_URL = "https://www.realtyapi.io/"
DEFAULT_MODELS = (
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash,"
    "gemini-3.5-flash,gemini-2.5-flash"
)


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


def init_command() -> int:
    root = _project_root()

    print("Keys by Friday setup")
    print("====================")

    uv = shutil.which("uv")
    if uv is None:
        print(
            "uv is required. Install it first: "
            "winget install --id=astral-sh.uv -e",
            file=sys.stderr,
        )
        return 1

    print("[1/3] Preparing Python environment...")
    subprocess.run([uv, "sync", "--extra", "dev"], cwd=root, check=True)

    env_path = root / ".env"
    existing = _read_env(env_path)

    print("\n[2/3] API keys")
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
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("\n[3/3] Done")
    print("Environment is ready and API keys were saved to .env.")
    print("Start the demo with:")
    print("  uv run adk web . --no-reload --port 8765")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kbf", description="Keys by Friday CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "init",
        help="Prepare the environment and configure API keys",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        return init_command()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
