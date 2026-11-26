from pathlib import Path

import pytest
import yaml

from reviewer.checks import ChecklistError, Group, load_checklist

TESTS_CI_IDS = [
    "ci_workflow_exists",
    "ci_runs_tests",
    "integration_tests_exist",
    "last_ci_run_passed",
]


def valid_check(check_id: str = "ci_workflow_exists") -> dict[str, object]:
    return {
        "id": check_id,
        "group": "tests_ci",
        "question": "Does the repository have a CI workflow?",
        "definition": "Pass when a workflow runs on push or pull request.",
        "evidence": "The workflow file.",
        "examples": {"pass": "ci.yml exists.", "fail": "None exists.", "unknown": "Unreadable."},
    }


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "checks.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_the_packaged_file_has_the_four_tests_and_ci_checks_in_order() -> None:
    checklist = load_checklist()

    assert [check.id for check in checklist.list_checks(Group.TESTS_CI)] == TESTS_CI_IDS
    assert [check.id for check in checklist.checks] == TESTS_CI_IDS


def test_every_packaged_check_has_text_for_each_field_and_result() -> None:
    for check in load_checklist().checks:
        assert check.question.endswith("?"), check.id
        assert len(check.definition) > 100, check.id
        assert check.evidence, check.id
        assert check.examples.pass_ and check.examples.fail and check.examples.unknown, check.id


def test_get_check_finds_by_id_and_rejects_an_unknown_id() -> None:
    checklist = load_checklist()

    assert checklist.get_check("last_ci_run_passed").group is Group.TESTS_CI
    with pytest.raises(KeyError, match="no_such_check"):
        checklist.get_check("no_such_check")


def test_a_group_with_no_checks_yet_is_empty() -> None:
    assert load_checklist().list_checks(Group.SECURITY) == []


def test_a_valid_file_on_disk_loads(tmp_path: Path) -> None:
    checklist = load_checklist(write(tmp_path, {"version": 2, "checks": [valid_check()]}))

    assert checklist.version == 2
    examples = checklist.get_check("ci_workflow_exists").examples
    assert examples.pass_ == "ci.yml exists."  # noqa: S105 (an example text, not a password)


def without(key: str) -> dict[str, object]:
    check = valid_check()
    del check[key]
    return check


def with_field(key: str, value: object) -> dict[str, object]:
    return valid_check() | {key: value}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"checks": [valid_check()]}, "version"),
        ({"version": 1, "checks": []}, "checks"),
        ({"version": 1, "checks": [valid_check(), valid_check()]}, "duplicate check ids"),
        ({"version": 1, "checks": [without("definition")]}, "definition"),
        ({"version": 1, "checks": [with_field("definition", "  ")]}, "definition"),
        ({"version": 1, "checks": [with_field("group", "performance")]}, "group"),
        ({"version": 1, "checks": [with_field("id", "Has CI")]}, "id"),
        ({"version": 1, "checks": [with_field("examples", {"pass": "a", "fail": "b"})]}, "unknown"),
        ({"version": 1, "checks": [with_field("weight", 3)]}, "weight"),
        (["not", "a", "mapping"], "checklist schema"),
        (None, "checklist schema"),
    ],
)
def test_a_malformed_file_is_rejected_with_the_reason(
    tmp_path: Path, data: object, message: str
) -> None:
    with pytest.raises(ChecklistError, match=message):
        load_checklist(write(tmp_path, data))


def test_a_file_that_is_not_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "checks.yaml"
    path.write_text("checks: [unclosed\n", encoding="utf-8")

    with pytest.raises(ChecklistError, match="not valid YAML"):
        load_checklist(path)


def test_a_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ChecklistError, match="cannot read"):
        load_checklist(tmp_path / "absent.yaml")
