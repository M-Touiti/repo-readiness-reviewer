"""The check definitions, loaded from `checks.yaml` and validated (ADR 0001).

The shape is the one `checklist-mcp` will serve in M2: `Checklist.list_checks(group)` and
`Checklist.get_check(id)` mirror its two tools, so the reviewer does not change when the file
moves behind the server.
"""

from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from reviewer.findings import CheckId

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Group(StrEnum):
    TESTS_CI = "tests_ci"
    DOCS_DESIGN = "docs_design"
    SECURITY = "security"


class Examples(BaseModel):
    """One example of each result, so the model sees what each looks like."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    pass_: Text = Field(alias="pass")
    fail: Text
    unknown: Text


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CheckId
    group: Group
    question: Text
    definition: Text
    evidence: Text = Field(description="What a pass or fail must cite.")
    examples: Examples


class Checklist(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    checks: list[Check] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [check.id for check in self.checks]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate check ids: {', '.join(duplicates)}")
        return self

    def list_checks(self, group: Group) -> list[Check]:
        """The checks of one group, in file order."""
        return [check for check in self.checks if check.group is group]

    def get_check(self, check_id: str) -> Check:
        for check in self.checks:
            if check.id == check_id:
                return check
        raise KeyError(f"no check with id {check_id!r}")


class ChecklistError(ValueError):
    """The checks file is missing, is not YAML, or does not match the schema."""


def load_checklist(path: Path | None = None) -> Checklist:
    """Load and validate `path`, or the `checks.yaml` shipped in the package."""
    source = path if path is not None else files("reviewer") / "checks.yaml"
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ChecklistError(f"cannot read {source}: {error}") from error
    except yaml.YAMLError as error:
        raise ChecklistError(f"{source} is not valid YAML: {error}") from error
    try:
        return Checklist.model_validate(data)
    except ValidationError as error:
        raise ChecklistError(f"{source} does not match the checklist schema:\n{error}") from error
