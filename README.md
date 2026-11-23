# repo-readiness-reviewer

Point it at a public repository: agents check tests, docs and security through MCP, and you get a report where
every finding links to its evidence.

> **Status (23 Nov 2026): planning. Nothing runs yet.** Milestone 1 (one reviewer and a CLI) is in progress; its
> task list is in [docs/ROADMAP.md](docs/ROADMAP.md).

## What exists today

| Piece | State |
|---|---|
| Roadmap, target architecture, M1 task breakdown | Written |
| Code, tests, CI | Not started |

## What it will do

Twelve yes-or-no checks in three groups (tests and CI, docs and design, security hygiene). Each finding is `pass`,
`fail` or `unknown`, with a file path or URL as evidence. `unknown` is allowed and counted; guessing is not.

## Limits

Public repositories only. No review of the source code itself, no automatic fixes or pull requests, no web
interface.
