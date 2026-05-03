from __future__ import annotations

import json
import os
import secrets
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _config_value(settings: dict | None, setting_key: str, env_key: str) -> str:
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return env_value
    if settings:
        return str(settings.get(setting_key) or "").strip()
    return ""


def google_oauth_enabled(settings: dict | None = None) -> bool:
    return bool(
        _config_value(settings, "google_oauth_client_id", "GOOGLE_OAUTH_CLIENT_ID")
        and _config_value(settings, "google_oauth_client_secret", "GOOGLE_OAUTH_CLIENT_SECRET")
    )


def generate_google_state() -> str:
    return secrets.token_urlsafe(32)


def get_google_redirect_uri(request, settings: dict | None = None) -> str:
    configured = _config_value(settings, "google_oauth_redirect_uri", "GOOGLE_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    return str(request.url_for("google_callback"))


def build_google_authorize_url(request, *, state: str, settings: dict | None = None) -> str:
    client_id = _config_value(settings, "google_oauth_client_id", "GOOGLE_OAUTH_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID no esta configurado.")
    params = {
        "client_id": client_id,
        "redirect_uri": get_google_redirect_uri(request, settings),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": _config_value(settings, "google_oauth_prompt", "GOOGLE_OAUTH_PROMPT") or "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_google_code(request, code: str, settings: dict | None = None) -> dict:
    payload = urlencode(
        {
            "code": code,
            "client_id": _config_value(settings, "google_oauth_client_id", "GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": _config_value(settings, "google_oauth_client_secret", "GOOGLE_OAUTH_CLIENT_SECRET"),
            "redirect_uri": get_google_redirect_uri(request, settings),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    http_request = Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(http_request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_google_userinfo(access_token: str) -> dict:
    http_request = Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urlopen(http_request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))
