from __future__ import annotations

import argparse
import json
from pathlib import Path

from .indexer import index_project
from .memory import record_memory, search_memory
from .retrieval import get_project_context


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hil", description="Harness Intelligence Layer")
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="Index a project")
    index.add_argument("project_root", nargs="?", default=".")

    context = commands.add_parser("context", help="Build a token-budgeted context package")
    context.add_argument("task")
    context.add_argument("project_root", nargs="?", default=".")
    context.add_argument("--budget", type=int, default=4000)
    context.add_argument(
        "--no-refresh",
        action="store_true",
        help="Use the stored index as-is instead of re-checking it against the working tree",
    )
    context.add_argument(
        "--embedding",
        choices=("off", "auto", "on", "hash"),
        default=None,
        help=(
            "Optional semantic re-ranking (default: HIL_EMBEDDINGS, else off). "
            "'auto'/'on' probe installed backends; 'hash' is the offline helper. "
            "Any unavailable backend degrades to local lexical retrieval."
        ),
    )

    search = commands.add_parser("memory-search", help="Search project memory")
    search.add_argument("query")
    search.add_argument("project_root", nargs="?", default=".")
    search.add_argument("--limit", type=int, default=5)

    record = commands.add_parser("memory-record", help="Record an engineering fact")
    record.add_argument("category")
    record.add_argument("title")
    record.add_argument("content")
    record.add_argument("project_root", nargs="?", default=".")
    record.add_argument("--tag", action="append", default=[])
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.project_root)
    try:
        if args.command == "index":
            _print(index_project(root))
        elif args.command == "context":
            _print(
                get_project_context(
                    args.task,
                    root,
                    args.budget,
                    refresh_index=not args.no_refresh,
                    embedding=args.embedding,
                )
            )
        elif args.command == "memory-search":
            _print(search_memory(args.query, root, args.limit))
        elif args.command == "memory-record":
            _print(record_memory(args.category, args.title, args.content, root, args.tag))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

