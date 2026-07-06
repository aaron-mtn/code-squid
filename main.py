"""Standalone Code Squid CLI entry point and command dispatcher."""

import sys

from cli.commands import run_cli


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
