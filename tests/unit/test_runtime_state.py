"""Runtime state lives in one per-user folder outside the repo, and the server/migration tooling uses it."""

import argparse
import importlib.util
from pathlib import Path

import pytest

from linkedin_agent import runtime, server
from linkedin_agent.linkedin import session

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_migration_script():
    spec = importlib.util.spec_from_file_location("migrate_runtime_state", REPO_ROOT / "scripts" / "migrate_runtime_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_dir_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(tmp_path / "home"))

    assert runtime.state_dir() == tmp_path / "home"
    assert session.auth_state_path() == tmp_path / "home" / "browser" / "state.json"
    assert session.lock_path() == tmp_path / "home" / "browser" / "linkedin.lock"
    assert runtime.langgraph_dir() == tmp_path / "home" / "langgraph"
    assert runtime.logs_dir() == tmp_path / "home" / "logs"


@pytest.mark.parametrize(("platform", "xdg", "expected"), [("darwin", None, "Library/Application Support/linkedin-agent"), ("linux", None, ".local/state/linkedin-agent"), ("linux", "/xdg", "/xdg/linkedin-agent")])
def test_state_dir_defaults_are_per_user_and_outside_the_repo(monkeypatch, tmp_path, platform, xdg, expected):
    monkeypatch.delenv("LINKEDIN_AGENT_HOME", raising=False)
    monkeypatch.setattr(runtime.sys, "platform", platform)
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    if xdg:
        monkeypatch.setenv("XDG_STATE_HOME", xdg)
    else:
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    state = runtime.state_dir()

    assert state == (Path(expected) if xdg else tmp_path / expected)
    assert REPO_ROOT not in state.parents


def test_daily_logs_go_to_the_runtime_folder(monkeypatch, tmp_path):
    import logging

    from linkedin_agent import daily

    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(tmp_path))
    loggers = [logging.getLogger(name) for name in ("daily_run", "invitations_manager", "inbox_manager", "unattended", "llm")]
    before = {logger.name: list(logger.handlers) for logger in loggers}
    try:
        daily.configure_file_logging()
        assert (tmp_path / "logs" / "daily_run.log").exists()
    finally:
        for logger in loggers:
            for handler in [h for h in logger.handlers if h not in before[logger.name]]:
                logger.removeHandler(handler)
                handler.close()


def test_server_runs_langgraph_from_the_runtime_folder(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(server.os, "chdir", lambda path: calls.setdefault("cwd", path))
    monkeypatch.setattr(server.os, "execv", lambda path, argv: calls.update(path=path, argv=argv))

    server.run_command(argparse.Namespace(port=2030))

    assert calls["cwd"] == tmp_path / "langgraph" and calls["cwd"].is_dir()
    assert calls["path"] == "/bin/langgraph"
    assert calls["argv"] == ["/bin/langgraph", "dev", "--config", str(server.LANGGRAPH_CONFIG), "--port", "2030", "--no-reload", "--no-browser"]


def test_server_config_loads_graphs_by_module_not_by_working_directory():
    import json

    config = json.loads(server.LANGGRAPH_CONFIG.read_text())

    assert config["graphs"] == {"invitation_review": "linkedin_agent.review.graphs:graph", "message_review": "linkedin_agent.review.graphs:message_graph"}
    assert config["source"] == {"kind": "uv", "root": ".."}
    assert (server.LANGGRAPH_CONFIG.parent / config["source"]["root"] / "pyproject.toml").exists()
    assert "dependencies" not in config and "env" not in config


def test_server_explains_a_missing_langgraph_cli(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit, match="uv sync --all-groups"):
        server.run_command(argparse.Namespace(port=2024))


def make_legacy_checkout(root: Path) -> None:
    (root / "playwright" / ".auth").mkdir(parents=True)
    (root / "playwright" / ".auth" / "state.json").write_text('{"cookies": []}')
    (root / "playwright" / ".auth" / "linkedin.lock").write_text("")
    (root / ".langgraph_api").mkdir()
    (root / ".langgraph_api" / ".langgraph_ops.pckl").write_bytes(b"ops")
    (root / "logs").mkdir()
    (root / "logs" / "daily_run.log").write_text("log")
    (root / ".superpowers" / "sdd").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "notes.md").write_text("notes")


def test_migration_moves_legacy_state_out_of_the_checkout(monkeypatch, tmp_path):
    migrate = load_migration_script()
    checkout, home = tmp_path / "checkout", tmp_path / "home"
    make_legacy_checkout(checkout)
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(home))
    monkeypatch.setattr(migrate, "server_is_running", lambda port=2024: False)

    assert migrate.main(["--checkout", str(checkout)]) == 0

    assert (home / "browser" / "state.json").read_text() == '{"cookies": []}'
    assert (home / "langgraph" / ".langgraph_api" / ".langgraph_ops.pckl").read_bytes() == b"ops"
    assert (home / "logs" / "daily_run.log").read_text() == "log"
    assert (home / "artifacts" / "superpowers" / "sdd" / "notes.md").read_text() == "notes"
    assert sorted(path.name for path in checkout.iterdir()) == []


def test_migration_never_overwrites_existing_runtime_data(monkeypatch, tmp_path):
    migrate = load_migration_script()
    checkout, home = tmp_path / "checkout", tmp_path / "home"
    make_legacy_checkout(checkout)
    (home / "browser").mkdir(parents=True)
    (home / "browser" / "state.json").write_text("newer session")
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(home))
    monkeypatch.setattr(migrate, "server_is_running", lambda port=2024: False)

    assert migrate.main(["--checkout", str(checkout)]) == 1

    assert (home / "browser" / "state.json").read_text() == "newer session"
    assert (checkout / "playwright" / ".auth" / "state.json").exists()


def test_migration_dry_run_changes_nothing_and_refuses_while_server_runs(monkeypatch, tmp_path):
    migrate = load_migration_script()
    checkout, home = tmp_path / "checkout", tmp_path / "home"
    make_legacy_checkout(checkout)
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(home))
    monkeypatch.setattr(migrate, "server_is_running", lambda port=2024: True)

    assert migrate.main(["--checkout", str(checkout), "--dry-run"]) == 0
    assert not home.exists()
    assert migrate.main(["--checkout", str(checkout)]) == 1
    assert (checkout / ".langgraph_api" / ".langgraph_ops.pckl").exists()
