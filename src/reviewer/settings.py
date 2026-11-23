"""Settings read from the environment and an optional `.env` file.

Secrets are held as `SecretStr`, so they never appear in a repr, a log line or a traceback.
Both are optional: replaying a recorded review and running the tests need neither. Code that
needs one asks for it through `require_anthropic_key` or `require_github_token`, which fail
with a message naming the missing variable.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingCredentialError(RuntimeError):
    """A live operation needs a credential that is not set."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    anthropic_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    @classmethod
    def load(cls, env_file: Path | None = Path(".env")) -> "Settings":
        """Read the environment, then `env_file` if it exists. `None` ignores any `.env` file."""
        return cls(_env_file=env_file)  # type: ignore[call-arg]

    def require_anthropic_key(self) -> SecretStr:
        return _require(self.anthropic_api_key, "ANTHROPIC_API_KEY")

    def require_github_token(self) -> SecretStr:
        return _require(self.github_token, "GITHUB_TOKEN")


def _require(value: SecretStr | None, name: str) -> SecretStr:
    if value is None or not value.get_secret_value().strip():
        raise MissingCredentialError(
            f"{name} is not set. Put it in the environment or in .env (see .env.example)."
        )
    return value
