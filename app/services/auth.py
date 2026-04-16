from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

from app.db import DATA_DIR, ensure_storage

PBKDF2_ITERATIONS = 390000
SESSION_SECRET_PATH = DATA_DIR / "session_secret.txt"
SESSION_COOKIE_NAME = "cotizaciones_session"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("La contrasena debe tener al menos 8 caracteres.")
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_text)
    except ValueError:
        return False

    calculated = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return hmac.compare_digest(calculated, digest)


def normalize_username(username: str) -> str:
    normalized = (username or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("El usuario debe tener entre 3 y 64 caracteres y solo usar letras, numeros, punto, guion o guion bajo.")
    return normalized


def validate_password_confirmation(password: str, confirm_password: str) -> None:
    if password != confirm_password:
        raise ValueError("Las contrasenas no coinciden.")
    if len(password) < 8:
        raise ValueError("La contrasena debe tener al menos 8 caracteres.")


def get_session_secret() -> str:
    secret_from_env = os.getenv("SESSION_SECRET", "").strip()
    if secret_from_env:
        return secret_from_env

    ensure_storage()
    if SESSION_SECRET_PATH.exists():
        return SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()

    generated = secrets.token_urlsafe(48)
    SESSION_SECRET_PATH.write_text(generated, encoding="utf-8")
    return generated


def https_only_sessions() -> bool:
    return os.getenv("SESSION_HTTPS_ONLY", "0").strip() == "1"


def build_session_token(user_id: int) -> str:
    payload = str(int(user_id))
    signature = hmac.new(
        get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def read_session_user_id(token: str | None) -> int | None:
    if not token or ":" not in token:
        return None

    payload, signature = token.split(":", 1)
    expected = hmac.new(
        get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        return int(payload)
    except ValueError:
        return None


def session_cookie_options() -> dict[str, object]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": https_only_sessions(),
        "path": "/",
    }
