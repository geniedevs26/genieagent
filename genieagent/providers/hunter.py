"""Hunter.io business email discovery and verification.

Rules enforced here:
* Only emails returned by Hunter are used - never a guessed address.
* ``valid`` is the only status treated as contactable; ``accept_all`` and
  ``unknown`` are stored but never marked verified.
* Verification timestamps and sources are preserved for audit.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Config, ConfigError
from ..http import ProviderError, Transport, request, require_ok
from ..normalize import (
    email_matches_domain,
    is_disposable,
    is_free_mail,
    is_generic_email,
    normalize_domain,
    normalize_email,
)
from ..util import now_iso


class HunterClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.hunter.io/v2",
        transport: Optional[Transport] = None,
        timeout: int = 45,
        pause: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ConfigError("HUNTER_API_KEY is missing.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self.pause = max(0.0, pause)
        self.sleep = sleep

    def _get(self, path: str, params: Dict[str, Any], action: str) -> Dict[str, Any]:
        query = dict(params)
        response = request(
            "GET",
            f"{self.base_url}/{path.lstrip('/')}",
            provider="hunter",
            headers={"Authorization": f"Bearer {self.api_key}"},
            params=query,
            timeout=self.timeout,
            retries=2,
            transport=self.transport,
        )
        if response.status == 202:
            # Hunter is still verifying; the documented behaviour is to poll.
            return {"data": {"status": "unknown", "pending": True}}
        payload = require_ok(response, "hunter", action)
        return payload if isinstance(payload, dict) else {}

    def domain_search(self, domain: str, limit: int = 10) -> List[Dict[str, Any]]:
        clean = normalize_domain(domain)
        if not clean:
            return []
        payload = self._get(
            "domain-search",
            {"domain": clean, "limit": max(1, min(100, int(limit)))},
            f"domain search for {clean}",
        )
        data = payload.get("data") or {}
        emails = data.get("emails") or []
        if self.pause:
            self.sleep(self.pause)
        return [email for email in emails if isinstance(email, dict)]

    def verify_email(self, email: str) -> Dict[str, Any]:
        clean = normalize_email(email)
        if not clean:
            return {"email": "", "status": "invalid", "score": 0, "error": "invalid email syntax"}
        payload = self._get("email-verifier", {"email": clean}, f"verification for {clean}")
        data = payload.get("data") or {}
        if self.pause:
            self.sleep(self.pause)
        return data

    # ------------------------------------------------------------------ mapping

    def choose_business_email(
        self, domain: str, candidates: Sequence[Dict[str, Any]], verify: bool = True
    ) -> Dict[str, Any]:
        """Pick the best business address and (optionally) verify it.

        Preference: valid generic business mailbox on the company domain, then a
        valid named contact on the company domain. Free mailboxes, disposable
        addresses and foreign domains are rejected.
        """
        scored: List[Tuple[float, Dict[str, Any], str]] = []
        for candidate in candidates:
            email = normalize_email(candidate.get("value") or candidate.get("email"))
            if not email:
                continue
            mail_domain = email.split("@")[-1]
            if is_free_mail(email) or is_disposable(email):
                continue
            if not email_matches_domain(email, domain):
                continue
            status = str(((candidate.get("verification") or {}).get("status")) or candidate.get("status") or "unknown").lower()
            confidence = _as_int(candidate.get("confidence") or candidate.get("score"))
            rank = {"valid": 300.0, "accept_all": 200.0, "unknown": 100.0, "invalid": 0.0}.get(status, 50.0)
            rank += 40.0 if is_generic_email(email) else 0.0
            rank += min(50.0, confidence / 2.0)
            sources = candidate.get("sources") or []
            source_url = ""
            if sources and isinstance(sources[0], dict):
                source_url = str(sources[0].get("uri") or sources[0].get("domain") or "")
            scored.append((rank, candidate, email))
        scored.sort(key=lambda item: item[0], reverse=True)
        for _, candidate, email in scored:
            status = str(((candidate.get("verification") or {}).get("status")) or "unknown").lower()
            verification_sources = _source_urls(candidate.get("sources"))
            result: Dict[str, Any] = {
                "email": email,
                "email_type": str(candidate.get("type") or ("generic" if is_generic_email(email) else "personal")),
                "email_status": status,
                "email_score": str(_as_int(candidate.get("confidence") or candidate.get("score"))),
                "email_verified_at": "",
                "email_source": "hunter_domain_search",
                "email_verification_sources": verification_sources,
                "contact_name": " ".join(
                    part for part in [str(candidate.get("first_name") or ""), str(candidate.get("last_name") or "")] if part
                ).strip(),
                "contact_title": str(candidate.get("position") or candidate.get("position_raw") or "").strip(),
            }
            if verify and status != "valid":
                checked = self.verify_email(email)
                checked_status = str(checked.get("status") or "unknown").lower()
                result["email_status"] = checked_status
                result["email_score"] = str(_as_int(checked.get("score")))
                result["email_source"] = "hunter_email_verifier"
                result["email_verification_sources"] = _source_urls(checked.get("sources")) or verification_sources
                verification_date = str((checked.get("verification") or {}).get("date") or "").strip()
                if checked_status in {"valid", "deliverable"}:
                    result["email_verified_at"] = _verification_timestamp(verification_date)
                if checked.get("accept_all") or checked_status == "accept_all":
                    result["email_status"] = "accept_all"
            elif status == "valid":
                result["email_verified_at"] = _verification_timestamp(
                    str((candidate.get("verification") or {}).get("date") or "")
                )
            if result["email_status"] not in {"valid", "deliverable"}:
                result["email_verified_at"] = ""
            return result
        return {
            "email": "",
            "email_type": "",
            "email_status": "not_found",
            "email_score": "0",
            "email_verified_at": "",
            "email_source": "hunter_domain_search",
            "email_verification_sources": [],
            "contact_name": "",
            "contact_title": "",
        }


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _source_urls(sources: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(sources, list):
        for source in sources[:5]:
            if isinstance(source, dict):
                url = source.get("uri") or source.get("domain")
                if url:
                    urls.append(str(url))
    return urls


def _verification_timestamp(date_text: str) -> str:
    if not date_text:
        return now_iso()
    try:
        return f"{date_text}T00:00:00Z"
    except Exception:  # pragma: no cover - defensive
        return now_iso()


def client_from_config(config: Config, transport: Optional[Transport] = None) -> HunterClient:
    return HunterClient(
        config.hunter_api_key,
        base_url=config.hunter_base_url,
        transport=transport,
        timeout=config.request_timeout,
        pause=config.request_pause,
    )
