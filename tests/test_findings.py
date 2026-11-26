import pytest
from pydantic import ValidationError

from reviewer.findings import Finding, Result, ReviewResult

SHA = "0123456789abcdef0123456789abcdef01234567"


def finding(**overrides: object) -> Finding:
    fields: dict[str, object] = {
        "check_id": "ci_workflow_exists",
        "result": "pass",
        "evidence": ".github/workflows/ci.yml",
        "reason": "The workflow runs on push and pull_request.",
    }
    fields.update(overrides)
    return Finding.model_validate(fields)


@pytest.mark.parametrize(
    "evidence",
    [
        ".github/workflows/ci.yml",
        "tests/integration",
        ".",
        "https://github.com/octocat/hello-world/actions/runs/123456",
    ],
)
def test_pass_and_fail_accept_a_path_or_an_https_url(evidence: str) -> None:
    assert finding(evidence=evidence).evidence == evidence
    assert finding(result="fail", evidence=evidence).result is Result.FAIL


@pytest.mark.parametrize("result", ["pass", "fail"])
@pytest.mark.parametrize("evidence", [None, "", "   "])
def test_pass_and_fail_need_evidence(result: str, evidence: str | None) -> None:
    with pytest.raises(ValidationError, match="evidence"):
        finding(result=result, evidence=evidence)


def test_unknown_needs_no_evidence_but_may_cite_some() -> None:
    assert finding(result="unknown", evidence=None).evidence is None
    assert finding(result="unknown", evidence="scripts/ci.sh").evidence == "scripts/ci.sh"


def test_unknown_with_blank_evidence_is_rejected_rather_than_kept() -> None:
    with pytest.raises(ValidationError, match="blank"):
        finding(result="unknown", evidence="")


@pytest.mark.parametrize(
    "evidence",
    [
        "/etc/passwd",
        "../other-repo/README.md",
        "docs/../../secret",
        "C:/Windows/win.ini",
        "tests\\integration",
        "http://github.com/octocat/hello-world",
        "ftp://example.com/file",
        "https://",
        " .github/workflows/ci.yml",
        "README.md\n",
    ],
)
def test_malformed_evidence_is_rejected(evidence: str) -> None:
    with pytest.raises(ValidationError, match="evidence"):
        finding(evidence=evidence)


@pytest.mark.parametrize(
    "overrides",
    [
        {"result": "maybe"},
        {"result": "PASS"},
        {"check_id": "CI Workflow"},
        {"check_id": ""},
        {"reason": ""},
        {"reason": "   "},
        {"reason": "x" * 501},
        {"confidence": 0.9},
    ],
)
def test_invalid_fields_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        finding(**overrides)


def test_a_finding_round_trips_through_json() -> None:
    original = finding()

    assert Finding.model_validate_json(original.model_dump_json()) == original
    assert original.model_dump(mode="json")["result"] == "pass"


def test_a_review_result_holds_one_finding_per_check() -> None:
    result = ReviewResult(
        repository="octocat/hello-world",
        commit=SHA,
        findings=[finding(), finding(check_id="ci_runs_tests")],
    )

    assert [f.check_id for f in result.findings] == ["ci_workflow_exists", "ci_runs_tests"]


def test_a_review_result_rejects_two_findings_for_one_check() -> None:
    with pytest.raises(ValidationError, match="two findings"):
        ReviewResult(repository="octocat/hello-world", commit=SHA, findings=[finding(), finding()])


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "octocat"},
        {"repository": "octocat/hello world"},
        {"repository": "https://github.com/octocat/hello-world"},
        {"commit": "main"},
        {"commit": SHA[:7]},
        {"commit": SHA.upper()},
    ],
)
def test_a_review_result_needs_owner_repo_and_a_full_sha(overrides: dict[str, str]) -> None:
    fields = {"repository": "octocat/hello-world", "commit": SHA, "findings": []} | overrides

    with pytest.raises(ValidationError):
        ReviewResult.model_validate(fields)
