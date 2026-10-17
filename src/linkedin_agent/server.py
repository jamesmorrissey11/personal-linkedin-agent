"""`linkedin-agent server`: run the LangGraph dev server that backs Agent Inbox.

The in-memory server keeps its review data in `.langgraph_api/` under its working directory, so it is started
from the per-user runtime folder (see `runtime.langgraph_dir`). Every checkout and worktree then sees the same
inbox, and nothing lands in the repo. Graphs are loaded by module name from `deploy/langgraph.json`.
"""

import argparse
import os
import shutil
from pathlib import Path

from linkedin_agent.runtime import langgraph_dir

LANGGRAPH_CONFIG = Path(__file__).resolve().parents[2] / "deploy" / "langgraph.json"
DEFAULT_PORT = 2024


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to serve on (default: {DEFAULT_PORT}).")


def server_argv(executable: str, port: int) -> list[str]:
    # --no-reload: a code edit must never restart the server in the middle of a LinkedIn action.
    return [executable, "dev", "--config", str(LANGGRAPH_CONFIG), "--port", str(port), "--no-reload", "--no-browser"]


def run_command(args: argparse.Namespace) -> int:
    executable = shutil.which("langgraph")
    if executable is None:
        raise SystemExit("The LangGraph CLI isn't installed. Run `uv sync --all-groups`, then `uv run linkedin-agent server`.")
    workdir = langgraph_dir()
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)
    os.execv(executable, server_argv(executable, args.port))
    return 0
