# src/geokit/secrets.py
from __future__ import annotations
import os
from typing import Optional

from dotenv import load_dotenv

# Load .env when this module is imported
load_dotenv()


class SecretNotFound(Exception):
    """Raised when a requested secret cannot be found."""

    pass


def _get_env(name: str) -> Optional[str]:
    # Convention: GEOKIT_<NAME>
    return os.getenv(f"GEOKIT_{name}")


def get_secret(name: str) -> str:
    """
    Main entrypoint for fetching secrets.

    For now, only looks at environment variables / .env.
    Later, you can extend this with a key vault.
    """
    value = _get_env(name)
    if value is not None:
        return value

    raise SecretNotFound(f"Secret '{name}' not set. Expected env var GEOKIT_{name}.")


# Convenience helpers for common secrets:
def get_spotinfo_username() -> str:
    return get_secret("SPOTINFO_USER")


def get_spotinfo_password() -> str:
    return get_secret("SPOTINFO_PASSWORD")


def get_spotinfo_base_url() -> str:
    return get_secret("SPOTINFO_BASE_URL")
