# 0002. One model module, with record and replay

- **Status:** accepted
- **Date:** 27 Nov 2026
- **Milestone:** M1

## Context

Every review calls Claude several times and reads a repository through the GitHub MCP server. Tests and CI must
run that path without an API key, without cost and without the network. Replaying model calls alone is not
enough: the model's next request contains the tool results it was given, and the reviewed repository changes
(its latest CI run most of all), so a replayed model call only matches if the tool results are replayed too
(M1 decision 2).

The Claude API rules for `claude-opus-5-5` also need one place to be enforced: thinking cannot be turned off
or given a budget, effort must be set, forced tool choice and `temperature` are rejected, assistant turns
must go back unchanged, and a refusal arrives as a stop reason, not an error.

## Decision

**1. `src/reviewer/model.py` is the only code that calls the model.** It reads `src/reviewer/model.yaml`:
model id, effort, `max_tokens`, the per-review spend cap and a price table. Model ids appear nowhere else.

**2. Three modes.** `live` calls Claude. `record` does the same and saves every exchange. `replay` serves
recorded exchanges back: it needs no key and builds no client, so it cannot reach the network, and a request
with no recording raises `ReplayMissError` instead of falling back to a live call.

**3. Fixture layout.** One directory per recorded review, one sub-directory per kind of exchange:

```text
<review>/
  model/<key>-<n>.json    one model call: {key, request, response}
  mcp/<key>-<n>.json      one MCP tool call (task 1.6), same shape
```

- `key` is the first 16 hex characters of the SHA-256 of the canonical request, serialised as JSON with
  sorted keys. For a model call the canonical request is the model id, effort, `max_tokens`, each message as
  the model sees it (type, content, tool calls, tool call id; message ids and metadata are left out), the tool
  schemas and the output format. For an MCP call it is the tool name and its arguments.
- `n` counts identical requests within one review (0, 1, ...), so a repeated request replays its answers in
  the order they were recorded.
- Exchanges are found by request, not by position, so the parallel reviewers of M2 can replay in any order.
- `record` refuses a directory that already holds recordings, so a re-recording never mixes old and new
  exchanges.
- The response is the LangChain message as a dictionary (`message_to_dict`), which round-trips content blocks
  (thinking blocks and their signatures included), tool calls, stop reason and usage. No credential, header
  or client setting is written.

**4. What invalidates a recording follows from the key.** Any change to the prompt, the checklist text in it,
a tool's name, description or schema, an MCP result, the model id, effort or `max_tokens` changes some request
and makes replay fail at that call. A bump of the Anthropic SDK or `langchain-anthropic` does not change the
key but can change what is sent; it is re-recorded too (`CLAUDE.md`). Re-recording spends money and is agreed
with the owner first.

**5. Structured output uses the API's own format.** Checked in the installed `langchain-anthropic` 1.7.12:
`with_structured_output(method="json_schema")` and `bind(output_config={"format": ...})` send
`output_config.format` with the schema converted by the SDK's `transform_schema`. The default
`method="function_calling"` forces a tool call, which `claude-opus-5-5` rejects; the library then drops the
forcing and warns. So the module sends the format itself (`invoke(..., output_schema=Model)`), and the caller
validates the answer with Pydantic, with one retry, then `unknown` (task 1.8). Constraints the API's format
does not accept (such as `pattern` and `maxLength` in `Finding`) are moved by `transform_schema` into the
field's description as text, so the model sees them but the API does not enforce them; that validation does.
`transform_schema` also drops a description that sits next to a `$ref` (`Finding.result`), so task 1.8 puts
the meaning of each result in the prompt as well.

**6. The request.** `thinking: {"type": "adaptive"}` is sent explicitly, with the default display (thinking
text omitted, signatures kept, so recordings stay small). `output_config.effort` comes from configuration
(`high`; the model's default is `medium`). No `temperature`, `top_p`, `top_k` or `tool_choice` is ever sent,
so tool choice is the API default, `auto`. Calls are not streamed; `max_tokens` is 16,000 and the
configuration rejects values above 32,000. A test pins this payload against the installed library.

**7. Cost.** Each call's cost comes from the API's own usage figures (uncached input, output, cache reads,
cache writes) and the price of the model that served the response; a response from a model with no price is
an error, not a zero. The spend cap is checked before each call: once spend reaches it, `SpendCapReached`
ends that reviewer with what it has. One call can overshoot the cap. Replay counts the recorded usage, so a
replayed review reports what the recording cost.

**8. Refusals are values.** The stop reason is read before the content. `stop_reason: "refusal"` returns
`Refused(category, explanation)` and the content is not used; the caller marks the affected checks `unknown`.
Server-side refusal fallbacks (`fallbacks` on the beta endpoint) are not enabled in M1: the pinned
`langchain-anthropic` does not handle fallback content blocks or per-model usage iterations, and a fallback
would answer a check with a model the configuration does not name. M3 measures the refusal rate on the
labelled set and decides then.

## Consequences

- CI replays whole reviews with no secrets and no cost, and a replay is exact or it fails at the first
  changed call, with the key that missed.
- Fixtures are reviewable JSON: a re-recording's diff shows what the model was asked and answered.
- Every prompt, checklist or tool change needs a paid re-recording in the same pull request. That is the
  point: an unrecorded change to what the model sees cannot reach `main` with green replay tests.
- Fixtures hold repository content and model output. They are public data about public repositories, but
  they are not edited by hand.
- A refusal costs the affected checks; there is no automatic second model.

## Alternatives considered

- **HTTP-level cassettes** (for example `vcrpy`). Rejected: they match on the SDK's raw request bodies and
  headers, tie fixtures to SDK internals, risk writing the key to disk, and do not cover MCP over stdio.
- **LangChain's model cache** (`set_llm_cache`). Rejected: it is a cache, not a replay; a miss silently calls
  the model, and it does not cover tool results.
- **Numbering exchanges by position.** Rejected: parallel branches make the order of calls vary between runs.
- **Structured output through a forced tool call.** Rejected: `claude-opus-5-5` does not accept forced tool
  choice (M1 decision 6).
