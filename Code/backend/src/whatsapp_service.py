from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from urllib import request

from .logging_service import get_logger

logger = get_logger("whatsapp_service")


def whatsapp_provider() -> str:
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
        return "twilio"
    if os.getenv("WHATSAPP_ACCESS_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID"):
        return "meta"
    return "disabled"


def whatsapp_enabled() -> bool:
    return whatsapp_provider() != "disabled"


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", str(value or ""))


def is_authorized_sender(number: str | None) -> bool:
    """Only numbers listed in WHATSAPP_ALLOWED_NUMBERS may control bids (fail closed)."""
    allowed = {_digits(n) for n in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if _digits(n)}
    return bool(allowed) and _digits(number) in allowed


def build_whatsapp_help() -> str:
    return (
        "WhatsApp bid bot commands:\n"
        "• BID depot=LUCKNOW qty=25 destination=ABC\n"
        "• STATUS\n"
        "• STOP ALL\n"
        "• STOP <job_id>\n"
        "• HELP"
    )


def parse_whatsapp_command(raw_text: str) -> dict[str, Any]:
    text = " ".join(str(raw_text or "").strip().split())
    if not text:
        return {"command": "help"}

    lower = text.lower()
    if lower in {"help", "menu", "hi", "hello"}:
        return {"command": "help"}

    normalized = text.replace("\n", " ")
    match = re.match(r"^(?:bid|start)\s+(.*)$", normalized, re.IGNORECASE)
    if match:
        payload = match.group(1)
        parts = payload.split()
        depot = None
        quantity = None
        destination = None

        for token in parts:
            if token.lower().startswith("depot="):
                depot = token.split("=", 1)[1].strip()
            elif token.lower().startswith("qty="):
                quantity = token.split("=", 1)[1].strip()
            elif token.lower().startswith("quantity="):
                quantity = token.split("=", 1)[1].strip()
            elif token.lower().startswith("destination="):
                destination = token.split("=", 1)[1].strip()
            elif token.lower().startswith("dest="):
                destination = token.split("=", 1)[1].strip()

        if len(parts) >= 3 and not depot and not any("=" in p for p in parts):
            depot = parts[0]
            quantity = parts[1]
            destination = " ".join(parts[2:])

        if not destination:
            for idx, token in enumerate(parts):
                if token.lower().startswith("dest="):
                    destination = token.split("=", 1)[1].strip()
                    break

        return {
            "command": "bid",
            "depot": depot,
            "quantity": quantity,
            "destination": destination,
        }

    if lower.startswith("status") or lower.startswith("check"):
        return {"command": "status"}

    if lower.startswith("stop"):
        remainder = text[4:].strip()
        if not remainder or remainder.lower() in {"all", "all bids", "all jobs"}:
            return {"command": "stop", "target": "all"}
        return {"command": "stop", "target": remainder}

    if lower.startswith("list"):
        return {"command": "status"}

    return {"command": "help"}


def _request_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def send_whatsapp_message(to_number: str, message: str) -> dict[str, Any]:
    provider = whatsapp_provider()
    if provider == "disabled":
        return {"status": "disabled", "message": "WhatsApp provider not configured"}

    if provider == "twilio":
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        if not account_sid or not auth_token or not from_number:
            return {"status": "error", "message": "Missing Twilio WhatsApp configuration"}

        try:
            data = {
                "From": from_number,
                "To": to_number,
                "Body": message,
            }
            encoded = (
                "&".join(f"{key}={__import__('urllib.parse').parse.quote(str(value))}" for key, value in data.items())
            ).encode("utf-8")
            req = request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                data=encoded,
                method="POST",
                headers={"Accept": "application/json"},
            )
            creds = f"{account_sid}:{auth_token}".encode("ascii")
            encoded_auth = base64.b64encode(creds).decode("ascii")
            req.add_header("Authorization", f"Basic {encoded_auth}")
            with request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {"status": "sent"}
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Twilio WhatsApp send failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    # Meta/WhatsApp Cloud API
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not access_token or not phone_number_id:
        return {"status": "error", "message": "Missing WhatsApp Cloud API configuration"}

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message},
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return _request_json(
            f"https://graph.facebook.com/v19.0/{phone_number_id}/messages",
            payload,
            headers,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Meta WhatsApp send failed: %s", exc)
        return {"status": "error", "message": str(exc)}
