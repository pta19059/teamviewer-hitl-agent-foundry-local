"""Interactive CLI host for the human-approved TeamViewer agent."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .agent import open_agent, run_turn
from .config import ConfigurationError, Settings
from .policy import APPROVAL_REQUIRED_TOOLS, READ_ONLY_TOOLS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="*", help="optional one-shot request")
    parser.add_argument(
        "--show-policy", action="store_true", help="print the MCP allow-list and exit"
    )
    return parser


def _print_policy() -> None:
    print("Read-only (no approval interruption):")
    for name in sorted(READ_ONLY_TOOLS):
        print(f"  {name}")
    print("\nState-changing (explicit approval for every call):")
    for name in sorted(APPROVAL_REQUIRED_TOOLS):
        print(f"  {name}")


async def _run(initial_prompt: str | None) -> None:
    settings = Settings.from_env()
    async with open_agent(settings) as agent:
        session = agent.create_session()
        if initial_prompt:
            print(await run_turn(agent, session, initial_prompt, settings))
            return

        print("TeamViewer HITL assistant. Type 'exit' to quit.")
        while True:
            prompt = input("\nYou: ").strip()
            if prompt.lower() in {"exit", "quit"}:
                return
            if not prompt:
                continue
            print(f"\nAgent: {await run_turn(agent, session, prompt, settings)}")


def main() -> None:
    args = _parser().parse_args()
    if args.show_policy:
        _print_policy()
        return

    try:
        asyncio.run(_run(" ".join(args.prompt).strip() or None))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        print("\nStopped. Unanswered approvals were not executed.")


if __name__ == "__main__":
    main()
