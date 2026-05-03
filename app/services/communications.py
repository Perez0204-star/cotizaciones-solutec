from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from app.db import fetch_settings


def email_delivery_enabled() -> bool:
    required = [
        os.getenv("SMTP_HOST", "").strip(),
        os.getenv("SMTP_USERNAME", "").strip(),
        os.getenv("SMTP_PASSWORD", "").strip(),
        os.getenv("SMTP_FROM", "").strip(),
    ]
    return all(required)


def send_password_recovery_email(recipient_email: str, recipient_name: str, code: str) -> None:
    settings = fetch_settings()
    org_name = (settings.get("org_name") or "Panel comercial").strip() or "Panel comercial"
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    sender_name = os.getenv("SMTP_FROM_NAME", org_name).strip() or org_name
    use_ssl = os.getenv("SMTP_USE_SSL", "0").strip() == "1"

    if not all([host, username, password, sender]):
        raise ValueError("La recuperacion por correo requiere configurar SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD y SMTP_FROM.")

    message = EmailMessage()
    message["Subject"] = f"Codigo de recuperacion - {org_name}"
    message["From"] = f"{sender_name} <{sender}>"
    message["To"] = recipient_email
    message.set_content(
        "\n".join(
            [
                f"Hola {recipient_name or 'usuario'},",
                "",
                "Recibimos una solicitud para restablecer tu acceso.",
                f"Tu codigo de recuperacion es: {code}",
                "",
                "Este codigo vence en 15 minutos.",
                "Si no solicitaste este cambio, puedes ignorar este mensaje.",
            ]
        )
    )

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as server:
            server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        if os.getenv("SMTP_STARTTLS", "1").strip() != "0":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.login(username, password)
        server.send_message(message)
