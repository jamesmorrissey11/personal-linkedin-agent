"""The `linkedin-agent` command: `invitations`, `inbox`, and `daily`.

Run with `uv run linkedin-agent <command> [options]`. Every command only reads LinkedIn and queues items
for review in Agent Inbox; LinkedIn actions happen only after a human decision there.
"""

import argparse
import sys

from dotenv import load_dotenv

from linkedin_agent.llm import MODEL_BACKENDS
from linkedin_agent.runtime import configure_console_logging


def build_parser() -> argparse.ArgumentParser:
    from linkedin_agent import daily, inbox, invitations

    parser = argparse.ArgumentParser(prog="linkedin-agent", description="Triage LinkedIn invitations and messages through Agent Inbox.")
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="{invitations,inbox,daily}")
    commands = [
        ("invitations", "Process LinkedIn invitations.", invitations),
        ("inbox", "Manage LinkedIn inbox messages.", inbox),
        ("daily", "Run the LinkedIn agents unattended (the scheduled daily sync).", daily),
    ]
    for name, description, module in commands:
        subparser = subcommands.add_parser(name, help=description, description=description)
        module.add_arguments(subparser)
        subparser.add_argument("--model-backend", choices=MODEL_BACKENDS, default=None, help="Model backend to use (default: MODEL_BACKEND env var, itself defaulting to 'ollama').")
        subparser.set_defaults(run_command=module.run_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    configure_console_logging()
    args = build_parser().parse_args(argv)
    return args.run_command(args)


if __name__ == "__main__":
    sys.exit(main())
