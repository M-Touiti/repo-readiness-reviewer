from pathlib import Path

import pytest
from typer.testing import CliRunner

import reviewer
from reviewer.cli import app
from reviewer.settings import MissingCredentialError, Settings


@pytest.fixture
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def test_package_exposes_its_version() -> None:
    assert reviewer.__version__ == "0.0.0"


@pytest.mark.usefixtures("no_credentials")
def test_settings_load_without_any_secret() -> None:
    settings = Settings.load(env_file=None)

    assert settings.anthropic_api_key is None
    assert settings.github_token is None


@pytest.mark.usefixtures("no_credentials")
def test_requiring_a_missing_credential_names_the_variable() -> None:
    settings = Settings.load(env_file=None)

    with pytest.raises(MissingCredentialError, match="ANTHROPIC_API_KEY"):
        settings.require_anthropic_key()
    with pytest.raises(MissingCredentialError, match="GITHUB_TOKEN"):
        settings.require_github_token()


@pytest.mark.usefixtures("no_credentials")
def test_a_blank_credential_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "   ")

    with pytest.raises(MissingCredentialError, match="GITHUB_TOKEN"):
        Settings.load(env_file=None).require_github_token()


@pytest.mark.usefixtures("no_credentials")
def test_secrets_are_read_from_the_environment_and_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-not-a-real-token")

    settings = Settings.load(env_file=None)

    assert settings.require_anthropic_key().get_secret_value() == "sk-test-not-a-real-key"
    assert settings.require_github_token().get_secret_value() == "ghp-test-not-a-real-token"
    shown = repr(settings) + str(settings)
    assert "sk-test-not-a-real-key" not in shown
    assert "ghp-test-not-a-real-token" not in shown


@pytest.mark.usefixtures("no_credentials")
def test_settings_read_a_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=from-dotenv\n", encoding="utf-8")

    settings = Settings.load(env_file=env_file)

    assert settings.require_github_token().get_secret_value() == "from-dotenv"


def test_cli_prints_its_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.0.0"


def test_cli_says_the_reviewer_is_not_implemented_yet() -> None:
    result = CliRunner().invoke(app, ["octocat/hello-world"])

    assert result.exit_code == 2
    assert "not implemented yet" in result.output
