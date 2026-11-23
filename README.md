# repo-readiness-reviewer

Point it at a public repository: agents check tests, docs and security through MCP, and you get a report where
every finding links to its evidence.

> **Status (23 Nov 2026): early. It does not review anything yet.** Milestone 1 (one reviewer and a CLI) is in
> progress; its task list is in [docs/ROADMAP.md](docs/ROADMAP.md).

## What exists today

| Piece | State |
|---|---|
| Roadmap, target architecture, M1 task breakdown | Written |
| Python package, locked dependencies, settings | Done: 8 tests |
| `review` command | Prints its version; the review itself is not implemented yet |
| CI | Not started |

## Development

Needs Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                   # install from uv.lock
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Credentials go in `.env` (copy `.env.example`); nothing that exists today needs them.

## What it will do

Twelve yes-or-no checks in three groups (tests and CI, docs and design, security hygiene). Each finding is `pass`,
`fail` or `unknown`, with a file path or URL as evidence. `unknown` is allowed and counted; guessing is not.

## Limits

Public repositories only. No review of the source code itself, no automatic fixes or pull requests, no web
interface.
