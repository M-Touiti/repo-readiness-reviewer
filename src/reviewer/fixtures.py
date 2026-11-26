"""Record and replay storage, shared by model calls and MCP tool results (ADR 0002).

A review's fixtures are one directory with one sub-directory per kind (`model/`, `mcp/`). Each
exchange is one JSON file named after the request: `<key>-<n>.json`, where `key` is a hash of the
canonical request and `n` counts identical requests within the review (0, 1, ...). Files are
found by request, not by position, so parallel branches can replay in any order.

Replay never falls through to the network: a request with no recording raises
`ReplayMissError`, which names the key so the missing exchange can be found.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any


class Mode(StrEnum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


class ReplayMissError(LookupError):
    """Replay was asked for an exchange that was never recorded."""


class FixtureError(RuntimeError):
    """The fixture directory cannot be used for the requested mode."""


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, non-ASCII kept as is."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_key(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest()[:16]


class FixtureStore:
    """One kind of exchange (`model` or `mcp`) under one review's fixture directory."""

    def __init__(self, root: Path, kind: str, mode: Mode) -> None:
        self.directory = root / kind
        self.mode = mode
        self._seen: Counter[str] = Counter()
        if mode is Mode.RECORD and self.directory.exists() and any(self.directory.iterdir()):
            raise FixtureError(
                f"{self.directory} already holds recordings; record into a new directory "
                "or delete it first, so old and new exchanges never mix"
            )
        if mode is Mode.REPLAY and not self.directory.is_dir():
            raise FixtureError(f"no recordings to replay: {self.directory} does not exist")

    def _next_path(self, request: Mapping[str, Any]) -> tuple[str, Path]:
        key = request_key(request)
        index = self._seen[key]
        self._seen[key] += 1
        return key, self.directory / f"{key}-{index}.json"

    def save(self, request: Mapping[str, Any], response: Any) -> Path:
        key, path = self._next_path(request)
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"key": key, "request": request, "response": response}
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, request: Mapping[str, Any]) -> Any:
        _, path = self._next_path(request)
        if not path.is_file():
            raise ReplayMissError(
                f"no recording {path.name} in {self.directory}: the request differs from "
                "every recorded one (prompt, tools, checklist, model settings or an earlier "
                "result changed), so the fixtures need re-recording"
            )
        return json.loads(path.read_text(encoding="utf-8"))["response"]
