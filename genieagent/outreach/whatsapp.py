"""WhatsApp provider adapters: Meta WhatsApp Cloud API and Green API.

Selected with ``WHATSAPP_PROVIDER=meta_cloud`` or ``WHATSAPP_PROVIDER=green_api``.
No adapter is enabled by default and none sends without an approved draft.

Reality checks kept in code (not hidden in docs):
* Meta Cloud API cannot start a conversation with free-form text outside the
  24-hour customer service window. First contact therefore requires an
  approved message template; without one the adapter refuses to send.
* Green API is an unofficial WhatsApp client. It is supported for owners who
  accept the account-risk and consent rules; it is never used by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import Config, ConfigError
from ..http import ProviderError, Transport, request, require_ok
from ..models import PROVIDER_GREEN, PROVIDER_META
from ..util import mask_phone


@dataclass
class WhatsAppSendResult:
    ok: bool
    status: str
    provider: str
    message_id: str = ""
    detail: str = ""
    mode: str = "text"


def normalize_phone(value: Any, default_country_code: str = "") -> str:
    """Return digits only (no plus). Never store or log a raw personal number."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and digits:
        return digits
    if raw.startswith("00") and len(digits) > 2:
        return digits[2:]
    if digits and raw.startswith("0") and default_country_code:
        return default_country_code + digits.lstrip("0")
    return digits


class MetaCloudProvider:
    name = PROVIDER_META

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        graph_version: str = "v25.0",
        template_name: str = "",
        template_lang: str = "en_US",
        transport: Optional[Transport] = None,
    ) -> None:
        if not phone_number_id or not access_token:
            raise ConfigError("Meta Cloud API needs WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN.")
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.graph_version = graph_version or "v25.0"
        self.template_name = template_name
        self.template_lang = template_lang or "en_US"
        self.transport = transport

    @property
    def ready(self) -> bool:
        return True

    @property
    def can_start_conversation(self) -> bool:
        """Meta blocks free-form first contact; only an approved template works."""
        return bool(self.template_name)

    def _endpoint(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}/{self.phone_number_id}/messages"

    def _post(self, payload: Dict[str, Any], retries: int = 0) -> Dict[str, Any]:
        response = request(
            "POST",
            self._endpoint(),
            provider="whatsapp_meta",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json_body=payload,
            retries=retries,
            transport=self.transport,
        )
        if response.status >= 400:
            detail = "Meta rejected the message"
            payload_error = response.json() if response.text else None
            if isinstance(payload_error, dict):
                error = payload_error.get("error") or {}
                detail = f"{detail}: {error.get('message') or error.get('code') or 'unknown error'}"
            raise ProviderError("whatsapp_meta", detail, status=response.status, body=response.text)
        data = require_ok(response, "whatsapp_meta", "send message")
        messages = data.get("messages") if isinstance(data, dict) else None
        return {"message_id": str((messages or [{}])[0].get("id") or "")}

    def send_text(self, to: str, text: str) -> WhatsAppSendResult:
        recipient = normalize_phone(to)
        if not recipient:
            return WhatsAppSendResult(False, "failed", self.name, detail="Recipient number is missing.")
        if not self.can_start_conversation:
            return WhatsAppSendResult(
                False,
                "blocked",
                self.name,
                detail=(
                    "Meta Cloud API requires an approved message template for first contact. "
                    "Set WHATSAPP_TEMPLATE_NAME after template approval, or choose another provider."
                ),
            )
        return self.send_template(recipient, [text[:900]])

    def send_template(self, to: str, body_params: List[str]) -> WhatsAppSendResult:
        recipient = normalize_phone(to)
        if not recipient:
            return WhatsAppSendResult(False, "failed", self.name, detail="Recipient number is missing.")
        if not self.template_name:
            return WhatsAppSendResult(False, "blocked", self.name, detail="WHATSAPP_TEMPLATE_NAME is not configured.")
        params = [{"type": "text", "text": str(value)[:300]} for value in body_params if str(value).strip()]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.template_lang},
                "components": [{"type": "body", "parameters": params}] if params else [],
            },
        }
        try:
            data = self._post(payload)
        except ProviderError as exc:
            return WhatsAppSendResult(False, "failed", self.name, detail=str(exc), mode="template")
        return WhatsAppSendResult(
            True,
            "accepted",
            self.name,
            message_id=data.get("message_id", ""),
            detail=f"Meta accepted the approved template for {mask_phone(recipient)}; delivery is not yet confirmed.",
            mode="template",
        )


class GreenAPIProvider:
    name = PROVIDER_GREEN

    def __init__(
        self,
        id_instance: str,
        api_token: str,
        base_url: str = "https://api.green-api.com",
        transport: Optional[Transport] = None,
    ) -> None:
        if not id_instance or not api_token:
            raise ConfigError("Green API needs GREEN_API_ID_INSTANCE and GREEN_API_TOKEN.")
        self.id_instance = id_instance
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    @property
    def ready(self) -> bool:
        return True

    @property
    def can_start_conversation(self) -> bool:
        return True

    def send_text(self, to: str, text: str) -> WhatsAppSendResult:
        recipient = normalize_phone(to)
        if not recipient:
            return WhatsAppSendResult(False, "failed", self.name, detail="Recipient number is missing.")
        url = f"{self.base_url}/waInstance{self.id_instance}/sendMessage/{self.api_token}"
        response = request(
            "POST",
            url,
            provider="whatsapp_green",
            json_body={"chatId": f"{recipient}@c.us", "message": str(text or "")[:4096]},
            retries=0,
            transport=self.transport,
        )
        if not response.ok:
            return WhatsAppSendResult(
                False,
                "failed",
                self.name,
                detail=f"Green API rejected the message (HTTP {response.status}).",
            )
        data = response.json() or {}
        message_id = str(data.get("idMessage") or "") if isinstance(data, dict) else ""
        return WhatsAppSendResult(
            True,
            "accepted",
            self.name,
            message_id=message_id,
            detail=f"Green API accepted the message for {mask_phone(recipient)}; delivery is not yet confirmed.",
        )


def build_provider(config: Config, transport: Optional[Transport] = None) -> Optional[Any]:
    if config.whatsapp_provider == "meta_cloud":
        return MetaCloudProvider(
            config.whatsapp_meta_phone_number_id,
            config.whatsapp_meta_token,
            graph_version=config.whatsapp_graph_version,
            template_name=config.whatsapp_meta_template_name,
            template_lang=config.whatsapp_meta_template_lang,
            transport=transport,
        )
    if config.whatsapp_provider == "green_api":
        return GreenAPIProvider(
            config.green_api_id_instance,
            config.green_api_token,
            base_url=config.green_api_base_url,
            transport=transport,
        )
    return None


def provider_status(config: Config) -> Dict[str, Any]:
    provider = build_provider(config) if config.whatsapp_ready else None
    return {
        "provider": config.whatsapp_provider,
        "configured": config.whatsapp_ready,
        "send_enabled": config.whatsapp_send_enabled,
        "can_start_conversation": bool(provider.can_start_conversation) if provider else False,
        "note": (
            "Meta Cloud API needs an approved template for first contact."
            if config.whatsapp_provider == "meta_cloud" and not config.whatsapp_meta_template_name
            else ""
        ),
    }
