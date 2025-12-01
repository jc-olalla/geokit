# src/geokit/io/base.py
from __future__ import annotations
from typing import Any, Dict, Optional
import requests

def create_basic_auth_session(
    username: str,
    password: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> requests.Session:
    """
    Generic helper to create a requests.Session with basic auth.
    """
    session = requests.Session()
    session.auth = (username, password)
    session.timeout = timeout  # you might also apply this per request
    if headers:
        session.headers.update(headers)
    return session

def build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

