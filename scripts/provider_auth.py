"""Runtime credentials and bounded model-access checks for the trial runners."""

import getpass
import http.client
import sys
import warnings
from urllib.parse import quote

KEY_LIMIT = 4096
KEY_ENV = {"codex": "CODEX_API_KEY", "claude": "ANTHROPIC_API_KEY"}
PROVIDERS = {"codex": "OpenAI", "claude": "Anthropic"}


def validate_key(value: object, agent: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= KEY_LIMIT
        or any(not 33 <= ord(character) <= 126 for character in value)
    ):
        raise ValueError(f"{PROVIDERS[agent]} API key is missing or malformed")
    return value


def prompt_provider_keys(agents: tuple[str, ...] = ("codex", "claude")) -> dict[str, str]:
    if not sys.stdin.isatty():
        raise ValueError("enter provider keys from an interactive terminal with hidden input")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return {
                agent: validate_key(
                    getpass.getpass(f"{PROVIDERS[agent]} trial API key (hidden): "), agent
                )
                for agent in agents
            }
        except getpass.GetPassWarning:
            raise ValueError("could not disable echo for provider key input") from None


def check_model_access(agent: str, model: str, key: str) -> None:
    """Check the direct provider endpoint without logging its response body."""
    if agent == "codex":
        host, headers = "api.openai.com", {"Authorization": f"Bearer {key}"}
    else:
        host = "api.anthropic.com"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    connection = http.client.HTTPSConnection(host, timeout=12)
    try:
        connection.request("GET", "/v1/models/" + quote(model, safe=""), headers=headers)
        status = connection.getresponse().status
    except (OSError, http.client.HTTPException):
        raise RuntimeError(f"{PROVIDERS[agent]} model preflight could not reach {host}") from None
    finally:
        connection.close()
    if status != 200:
        raise RuntimeError(f"{PROVIDERS[agent]} model preflight failed for {model} (HTTP {status})")
