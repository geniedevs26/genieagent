"""Brevo SMTP delivery plus optional Brevo event tracking.

SMTP acceptance is *not* delivery. Records are always marked
``smtp_accepted`` and only provider events may upgrade that to ``delivered``.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Callable, Dict, List, Optional

from ..config import Config
from ..http import ProviderError, Transport, request, require_ok

BREVO_EVENTS_URL = "https://api.brevo.com/v3/smtp/statistics/events"


@dataclass
class EmailSendResult:
    ok: bool
    status: str
    provider_message_id: str = ""
    detail: str = ""
    accepted: Optional[List[str]] = None
    refused: Optional[List[str]] = None


class BrevoSMTP:
    """Thin, non-retrying SMTP client (a retry could duplicate a message)."""

    def __init__(
        self,
        host: str,
        port: int,
        login: str,
        password: str,
        sender_email: str,
        sender_name: str = "",
        timeout: int = 30,
        smtp_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.login = login
        self.password = password
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.timeout = timeout
        self._smtp_factory = smtp_factory

    @property
    def ready(self) -> bool:
        return bool(self.host and self.login and self.password and self.sender_email)

    def _connect(self) -> Any:
        if self._smtp_factory is not None:
            return self._smtp_factory(self.host, self.port, timeout=self.timeout)
        if self.port == 465:
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
        client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        return client

    def build_message(self, to: str, subject: str, body: str, reply_to: str = "") -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self.sender_name or "GenieDevs", self.sender_email))
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=self.sender_email.split("@")[-1] or None)
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body)
        return message

    def send(self, to: str, subject: str, body: str, reply_to: str = "", dry_run: bool = False) -> EmailSendResult:
        if not self.ready:
            return EmailSendResult(False, "failed", detail="Brevo SMTP is not configured.")
        if not to or "@" not in to:
            return EmailSendResult(False, "failed", detail="Recipient email is missing or invalid.")
        message = self.build_message(to, subject, body, reply_to=reply_to)
        if dry_run:
            return EmailSendResult(
                True,
                "dry_run",
                detail=f"Dry run: message to {_domain(to)} was prepared but not sent.",
                accepted=[to],
            )
        try:
            with self._connect() as client:
                client.login(self.login, self.password)
                refused = client.send_message(message) or {}
            refused_addresses = [str(address) for address in refused.keys()]
            if refused_addresses:
                return EmailSendResult(
                    False,
                    "failed",
                    detail="SMTP refused the recipient.",
                    accepted=[to] if not refused_addresses else [],
                    refused=refused_addresses,
                )
            return EmailSendResult(
                True,
                "smtp_accepted",
                provider_message_id=str(message.get("Message-ID") or ""),
                detail="Brevo SMTP accepted the message; delivery is not yet confirmed.",
                accepted=[to],
            )
        except smtplib.SMTPAuthenticationError:
            return EmailSendResult(False, "failed", detail="Brevo SMTP authentication failed. Check BREVO_SMTP_LOGIN/BREVO_SMTP_KEY.")
        except (smtplib.SMTPException, socket.timeout, OSError, ssl.SSLError) as exc:
            return EmailSendResult(
                False,
                "unknown",
                detail=f"SMTP send outcome is ambiguous ({type(exc).__name__}); review before retrying.",
            )


def _domain(address: str) -> str:
    return str(address or "").split("@")[-1] or "recipient"


def smtp_from_config(config: Config, smtp_factory: Optional[Callable[..., Any]] = None) -> BrevoSMTP:
    return BrevoSMTP(
        config.brevo_smtp_host,
        config.brevo_smtp_port,
        config.brevo_smtp_login,
        config.brevo_smtp_key,
        config.sender_email,
        config.brevo_sender_name or config.owner_name,
        smtp_factory=smtp_factory,
    )


# ------------------------------------------------------------------ tracking


def fetch_email_events(
    api_key: str,
    email: str,
    limit: int = 50,
    transport: Optional[Transport] = None,
) -> List[Dict[str, Any]]:
    """Read Brevo transactional events for one address (requires BREVO_API_KEY)."""
    if not api_key:
        raise ProviderError("brevo", "BREVO_API_KEY is not configured")
    response = request(
        "GET",
        BREVO_EVENTS_URL,
        provider="brevo",
        headers={"api-key": api_key, "Accept": "application/json"},
        params={"email": email, "limit": max(1, min(100, int(limit))), "sort": "desc"},
        retries=2,
        transport=transport,
    )
    payload = require_ok(response, "brevo", "event listing")
    events = payload.get("events") if isinstance(payload, dict) else None
    return [event for event in (events or []) if isinstance(event, dict)]


def delivery_status_from_events(events: List[Dict[str, Any]]) -> str:
    """Collapse Brevo events into one delivery status (most specific wins)."""
    names = {str(event.get("event") or "").lower() for event in events}
    if names & {"hard_bounce", "blocked", "spam", "invalid_email"}:
        return "bounced"
    if "delivered" in names:
        return "delivered"
    if names & {"soft_bounce", "deferred"}:
        return "deferred"
    if names & {"opened", "clicks", "unique_opened"}:
        return "delivered"
    if "request" in names or "sent" in names:
        return "smtp_accepted"
    return ""
