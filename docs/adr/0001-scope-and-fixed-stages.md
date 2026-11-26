# 0001. Scope and fixed stages

- **Status:** accepted
- **Date:** 26 Nov 2026
- **Milestone:** M1

## Context

"Is this repository ready for production?" has no single answer, and a model asked the open question will
always produce one: fluent, plausible and impossible to check or compare between runs. To be useful the review
has to be narrow enough that every answer can be verified by a person in a minute, and stable enough that it can
be scored against a labelled set (M3).

The same applies to how the work is organised. Multi-agent frameworks make it easy to let models hand work to one
another and decide when they are done. That buys flexibility this problem does not need: the work is a known list
of questions that split into independent groups.

## Decision

**1. A fixed checklist of twelve yes-or-no checks**, in three groups of four:

| Group | Checks |
|---|---|
| Tests and CI | A CI workflow exists; CI runs tests; integration tests exist; the default branch's last CI run passed |
| Docs and design | The README explains how to run it; the architecture is described; design decisions are recorded; a licence is present |
| Security hygiene | Dependency updates are automated; no secrets-like files are committed; a security policy or scanning workflow exists; dependencies are pinned or locked |

Each check has a written definition, the evidence it requires and an example of each result. The definitions are
data, not prompt text: in M1 they live in `src/reviewer/checks.yaml`, and from M2 they are served by
`checklist-mcp`. Changing a rule changes the data, not a prompt. A check is added or removed only by a new ADR.

**2. Three result values: `pass`, `fail`, `unknown`.**

- `pass` and `fail` must cite evidence: a file path or a URL in the reviewed repository, pinned to the commit the
  review read. A finding without evidence is not valid.
- `unknown` means the evidence was not found, could not be read, or does not settle the question. It is a valid
  result and it is counted and reported; it is never treated as an error to hide.
- When in doubt the answer is `unknown`. A wrong `pass` or `fail` costs more than an honest `unknown`, and the
  evaluation (M3) scores it that way.

**3. Fixed stages: code routes, models read and judge.**

The order of the work is written in code as a LangGraph graph with fixed nodes and edges. No model decides which
agent runs next, whether to stop, or whether to post. Models do two things only: read the repository through
allowlisted read-only tools, and judge a check against its definition, returning schema-validated findings.
The stages, as built up over the milestones:

1. resolve the repository to one commit;
2. plan: choose which of the twelve checks apply (it can drop a check that cannot apply, never add one);
3. review: one reviewer per group, each with its own checks, tools and tool-call cap;
4. write the report (no tools);
5. evidence check (plain code, no model): a `pass` or `fail` whose cited path does not exist becomes `unknown`;
6. approval: a human approves or rejects posting;
7. post, on approval only, to a sandbox repository the operator owns, never to the reviewed project.

M1 builds stages 1 and 3 with one reviewer (Tests and CI). The exact shape of the graph once there are three
reviewers (fan-out, merging, failure isolation) is ADR 0003.

**4. Out of scope:** review of the source code itself (quality, bugs, style), private repositories, automatic
fixes or pull requests, and a web interface.

## Consequences

- Every finding can be checked by opening one link, and reviews of the same commit can be compared and scored.
- The tool says nothing about anything outside the twelve checks, however obvious. A repository can pass all
  twelve and still be poor; the README states this limit.
- Yes-or-no checks lose nuance (a CI workflow that runs one trivial test passes "CI runs tests"). Accepted: the
  definitions say what counts, and a finer judgement would need a scale that cannot be labelled reliably.
- A high `unknown` share is a visible, measured weakness rather than hidden guessing; the evaluation report
  publishes it.
- Because routing is code, the graph is testable without a model: fake reviewers and fake tools exercise every
  path, and replayed fixtures (ADR 0002) reproduce a real review exactly.
- Adding a group or check is a deliberate change: data, a new ADR, labels in the evaluation set, and re-recorded
  fixtures.

## Alternatives considered

- **Open-ended review** ("assess this repository's production readiness"). Rejected: answers cannot be verified,
  compared between runs or scored.
- **A score per area** (for example 1 to 5). Rejected: labelling a scale consistently is much harder than
  labelling yes or no, and a number hides which evidence it rests on.
- **Two result values**, forcing `pass` or `fail`. Rejected: it turns missing evidence into guesses.
- **Free handoffs between agents**, where models choose the next agent and when to stop. Rejected for this
  problem: the work is a fixed list split into independent groups, so model routing adds cost, failure modes and
  nondeterminism, and makes replay and testing harder, for no gain in what is found.
