"""What a review returns: one finding per check, each `pass`, `fail` or `unknown` (ADR 0001).

`pass` and `fail` must cite evidence; `unknown` may cite some but need not. Evidence is either an
`https://` URL (a workflow run, for example) or a path relative to the repository root, read at the
reviewed commit. In M1 the schema only checks that evidence is present and well formed; whether a
cited path exists at that commit is the evidence check's job (M2).

These models are also what the reviewer's structured answer is validated against (task 1.8), so
they stay plain: string fields, one enum, no custom JSON schema.
"""

import re
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CHECK_ID_PATTERN = r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"
REPOSITORY_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
COMMIT_PATTERN = r"^[0-9a-f]{40}$"

CheckId = Annotated[str, StringConstraints(pattern=CHECK_ID_PATTERN, max_length=64)]


class Result(StrEnum):
    PASS = "pass"  # noqa: S105 (a result value, not a password)
    FAIL = "fail"
    UNKNOWN = "unknown"


class Finding(BaseModel):
    """The answer to one check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: CheckId = Field(description="The id of the check this finding answers.")
    result: Result = Field(
        description="pass or fail only with evidence; unknown when the evidence does not settle it."
    )
    evidence: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "A path relative to the repository root, or an https:// URL. "
            "Required for pass and fail."
        ),
    )
    reason: str = Field(
        min_length=1, max_length=500, description="One or two sentences: why this result."
    )

    @model_validator(mode="after")
    def _evidence_rules(self) -> Self:
        if self.evidence is not None:
            problem = evidence_problem(self.evidence)
            if problem:
                raise ValueError(f"evidence {self.evidence!r}: {problem}")
        elif self.result is not Result.UNKNOWN:
            raise ValueError(f"a {self.result.value} finding needs evidence, or use unknown")
        if not self.reason.strip():
            raise ValueError("reason is blank")
        return self


class ReviewResult(BaseModel):
    """All findings of one review, pinned to the commit that was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: Annotated[str, StringConstraints(pattern=REPOSITORY_PATTERN)] = Field(
        description="owner/repo"
    )
    commit: Annotated[str, StringConstraints(pattern=COMMIT_PATTERN)] = Field(
        description="The full SHA every read and every evidence link refers to."
    )
    findings: list[Finding]

    @model_validator(mode="after")
    def _one_finding_per_check(self) -> Self:
        seen: set[str] = set()
        for finding in self.findings:
            if finding.check_id in seen:
                raise ValueError(f"two findings for check {finding.check_id!r}")
            seen.add(finding.check_id)
        return self


_URL = re.compile(r"^https://[^\s/]+/\S*$")


def evidence_problem(evidence: str) -> str | None:
    """Why `evidence` is not a usable path or URL, or `None` if it is."""
    if not evidence.strip():
        return "is blank"
    if evidence != evidence.strip() or any(c in evidence for c in "\r\n\t"):
        return "has surrounding or control whitespace"
    if "://" in evidence:
        return None if _URL.match(evidence) else "a URL must be https:// with a host"
    if evidence.startswith("/") or "\\" in evidence or re.match(r"^[A-Za-z]:", evidence):
        return "a path must be relative to the repository root, with forward slashes"
    if ".." in evidence.split("/"):
        return "a path must not leave the repository"
    return None
