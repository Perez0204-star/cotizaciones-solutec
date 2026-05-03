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
RECOVERY_CODE_PATH = DATA_DIR / "recovery_code.txt"
SESSION_COOKIE_NAME = "cotizaciones_session"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if normalized and not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Ingresa un correo electronico valido.")
    return normalized


def normalize_identity(identity: str) -> str:
    normalized = (identity or "").strip().lower()
    if not normalized:
        raise ValueError("Ingresa tu usuario o correo electronico.")
    if "@" in normalized:
        return normalize_email(normalized)
    return normalize_username(normalized)


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


def _format_recovery_code(raw: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    groups = [sanitized[index : index + 4] for index in range(0, len(sanitized), 4)]
    return "-".join(group for group in groups if group)


def get_recovery_code() -> str:
    code_from_env = os.getenv("RECOVERY_CODE", "").strip()
    if code_from_env:
        return _format_recovery_code(code_from_env)

    ensure_storage()
    if RECOVERY_CODE_PATH.exists():
        return _format_recovery_code(RECOVERY_CODE_PATH.read_text(encoding="utf-8").strip())

    generated = _format_recovery_code(secrets.token_hex(8))
    RECOVERY_CODE_PATH.write_text(generated, encoding="utf-8")
    return generated


def verify_recovery_code(candidate: str) -> bool:
    expected = get_recovery_code()
    normalized_candidate = _format_recovery_code(candidate)
    return bool(normalized_candidate) and hmac.compare_digest(normalized_candidate, expected)


def generate_email_recovery_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_ephemeral_code(code: str) -> str:
    digest = hmac.new(
        get_session_secret().encode("utf-8"),
        (code or "").strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def verify_ephemeral_code(candidate: str, expected_hash: str) -> bool:
    normalized = (candidate or "").strip()
    if not normalized or not expected_hash:
        return False
    return hmac.compare_digest(hash_ephemeral_code(normalized), expected_hash)


def derive_username_from_email(email: str) -> str:
    normalized = normalize_email(email)
    local_part = normalized.split("@", 1)[0]
    slug = re.sub(r"[^a-z0-9._-]+", "-", local_part.lower()).strip(".-_")
    slug = slug or "usuario"
    slug = slug[:52]
    suffix = secrets.token_hex(3)
    candidate = f"{slug}-{suffix}"
    return normalize_username(candidate)


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
