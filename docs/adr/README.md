# Architecture decision records

One file per decision, numbered in order. An accepted ADR is never edited: a changed decision gets a new ADR that
supersedes it, and both rows here say so.

| # | Decision | Status |
|---|---|---|
| [0001](0001-scope-and-fixed-stages.md) | Scope and fixed stages: twelve yes-or-no checks, `pass`/`fail`/`unknown` with evidence, code routes and models only read and judge | accepted, 26 Nov 2026 |
| [0002](0002-record-and-replay.md) | One model module with record and replay of model calls and MCP tool results; the fixture layout; structured output in the API's format; refusals as values, no server-side fallback in M1 | accepted, 27 Nov 2026 |
| 0003 | A supervisor with fixed stages and parallel reviewers, not free handoffs | planned, M2 |
