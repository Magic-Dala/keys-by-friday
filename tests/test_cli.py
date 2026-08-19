from __future__ import annotations

from pathlib import Path

import rental_agent.cli as cli


def test_parser_exposes_friendly_commands() -> None:
    parser = cli.build_parser()

    start = parser.parse_args(["start"])
    assert start.command == "start"
    assert start.frontend_port == 3000
    assert start.backend_port == 8000

    agent = parser.parse_args(["agent"])
    assert agent.command == "agent"
    assert agent.port == 8765


def test_parser_rejects_invalid_ports() -> None:
    parser = cli.build_parser()
    try:
        parser.parse_args(["start", "--backend-port", "70000"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("invalid port should be rejected")


def test_init_prepares_full_product(monkeypatch, tmp_path: Path, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}\n", encoding="utf-8")

    commands: list[tuple[list[str], Path]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/{name}")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, *, cwd, check, **kwargs: commands.append((command, cwd)),
    )
    secrets = iter(["gemini-key", "realty-key"])
    monkeypatch.setattr(cli, "_read_secret", lambda *args, **kwargs: next(secrets))

    assert cli.init_command() == 0

    assert commands[0][0] == [
        "/uv",
        "sync",
        "--frozen",
        "--extra",
        "dev",
        "--extra",
        "backend",
    ]
    assert commands[0][1] == tmp_path
    assert commands[1] == (["/npm", "ci"], frontend)
    assert commands[2] == (["/uv", "tool", "install", "--editable", "."], tmp_path)

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=gemini-key" in env
    assert "REALTYAPI_API_KEY=realty-key" in env
    assert "LISTING_PROVIDER=realtyapi" in env
    assert "AGENT_MODE=adk" in env
    assert "FRONTEND_ORIGIN=http://localhost:3000" in env
    assert "GEMINI_SEARCH_MODEL" not in env
    assert "GEMINI_MODELS" not in env

    frontend_env = (frontend / ".env.local").read_text(encoding="utf-8")
    assert frontend_env == "NEXT_PUBLIC_BACKEND_URL=http://localhost:8000\n"

    output = capsys.readouterr().out
    assert "kbf init" in output
    assert ".\\kbf init" in output
    assert "kbf start" in output
    assert ".\\kbf start" in output
    assert "kbf agent" in output
    assert ".\\kbf agent" in output


def test_init_preserves_vertex_ai_auth_and_removes_legacy_model_overrides(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "GOOGLE_API_KEY=",
                "GEMINI_API_KEY=",
                "GOOGLE_GENAI_USE_VERTEXAI=TRUE",
                "GOOGLE_CLOUD_PROJECT=vertex-project",
                "GOOGLE_CLOUD_LOCATION=global",
                "GOOGLE_MAPS_API_KEY=maps-key",
                "AUTH_MODE=firebase",
                "GEMINI_SEARCH_MODEL=user-selected-search-model",
                "GEMINI_MODELS=user-selected-model-a,user-selected-model-b",
                "REALTYAPI_API_KEY=existing-realty-key",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/{name}")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: None)

    secret_prompts: list[str] = []

    def fake_read_secret(prompt: str, existing: str | None = None) -> str:
        secret_prompts.append(prompt)
        if prompt == "RealtyAPI key":
            assert existing == "existing-realty-key"
            return "updated-realty-key"
        raise AssertionError("Vertex AI initialization must not request a Gemini API key")

    monkeypatch.setattr(cli, "_read_secret", fake_read_secret)

    assert cli.init_command() == 0

    env = cli._read_env(tmp_path / ".env")
    assert env["GOOGLE_GENAI_USE_VERTEXAI"] == "TRUE"
    assert env["GOOGLE_CLOUD_PROJECT"] == "vertex-project"
    assert env["GOOGLE_CLOUD_LOCATION"] == "global"
    assert env["GOOGLE_MAPS_API_KEY"] == "maps-key"
    assert env["AUTH_MODE"] == "firebase"
    assert env["REALTYAPI_API_KEY"] == "updated-realty-key"
    assert "GEMINI_SEARCH_MODEL" not in env
    assert "GEMINI_MODELS" not in env
    assert secret_prompts == ["RealtyAPI key"]


def test_start_requires_init(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "frontend").mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/{name}")

    try:
        cli.start_command(3000, 8000)
    except SystemExit as error:
        assert str(error) == "Project is not initialized. Run `kbf init` first."
    else:
        raise AssertionError("start_command should require initialization")


def test_start_stops_both_services_on_keyboard_interrupt(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("GOOGLE_API_KEY=test\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    backend = FakeProcess(1)
    frontend_process = FakeProcess(2)
    processes = iter([backend, frontend_process])
    terminated: list[FakeProcess] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/{name}")
    monkeypatch.setattr(cli, "_require_available_port", lambda *args: None)
    monkeypatch.setattr(cli, "_start_process", lambda *args, **kwargs: next(processes))
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_terminate_process", terminated.append)
    monkeypatch.setattr(cli.time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert cli.start_command(3000, 8000) == 0
    assert terminated == [frontend_process, backend]


def test_agent_command_wraps_adk_web(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("GOOGLE_API_KEY=test\n", encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/{name}")
    monkeypatch.setattr(cli, "_require_available_port", lambda *args: None)
    monkeypatch.setattr(
        cli.subprocess,
        "call",
        lambda command, *, cwd: calls.append((command, cwd)) or 0,
    )

    assert cli.agent_command(8765) == 0
    assert calls == [
        (["/uv", "run", "adk", "web", ".", "--no-reload", "--port", "8765"], tmp_path)
    ]
