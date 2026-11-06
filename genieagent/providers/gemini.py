"""Gemini lead analysis, qualification and outreach drafting.

Uses the current stable Flash model (``gemini-3.8-flash``) with structured JSON
output. The model never supplies facts: prompts require it to use only the
evidence provided, and every response is validated before it is stored.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from ..config import Config, ConfigError, ensure_supported_model
from ..http import ProviderError, Transport, request, require_ok
from ..models import BANNED_DRAFT_MARKERS
from ..util import now_iso

QUALIFICATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "qualified": {"type": "boolean"},
        "score": {"type": "integer"},
        "service_fit": {"type": "string"},
        "need_summary": {"type": "string"},
        "reasoning": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "recommended_angle": {"type": "string"},
        "evidence_quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["qualified", "score", "service_fit", "reasoning"],
}

DRAFT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "email_body": {"type": "string"},
        "whatsapp_body": {"type": "string"},
        "personalization_notes": {"type": "string"},
    },
    "required": ["subject", "email_body"],
}

SYSTEM_RULES = (
    "You are a careful B2B research assistant. Use only the facts in the supplied record. "
    "Never invent company details, budgets, names, past work, client results or email addresses. "
    "If evidence is thin, lower the score and say what is missing. Return JSON only."
)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        transport: Optional[Transport] = None,
        timeout: int = 90,
    ) -> None:
        if not api_key:
            raise ConfigError("GEMINI_API_KEY is missing.")
        self.api_key = api_key
        self.model = ensure_supported_model(model)
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout

    # ---------------------------------------------------------------- transport

    def _generate(self, prompt: str, schema: Dict[str, Any], max_output_tokens: int = 2048) -> Dict[str, Any]:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_RULES}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "maxOutputTokens": max_output_tokens,
            },
        }
        url = f"{self.base_url}/models/{self.model}:generateContent"
        response = request(
            "POST",
            url,
            provider="gemini",
            headers={"x-goog-api-key": self.api_key},
            json_body=body,
            timeout=self.timeout,
            retries=2,
            transport=self.transport,
        )
        payload = require_ok(response, "gemini", "generateContent")
        feedback = payload.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise ProviderError("gemini", f"prompt blocked: {feedback.get('blockReason')}")
        text = extract_text(payload)
        if not text:
            raise ProviderError("gemini", "empty response text")
        return parse_json_object(text)

    # ------------------------------------------------------------------ prompts

    def qualify_lead(self, lead: Dict[str, Any], min_score: int = 70) -> Dict[str, Any]:
        evidence = _evidence_text(lead)
        if not evidence:
            raise ProviderError("gemini", "lead has no usable requirement evidence; refusing to qualify")
        prompt = (
            "Qualify this business lead for a freelance web/AI/automation service provider.\n"
            "Score 0-100 for genuine business need and service suitability.\n"
            "A score >= %d means worth a human review and a personalized draft.\n"
            "Reject job-board ads, unpaid requests, seller advertisements and vague interest.\n\n"
            "LEAD RECORD (only source of truth):\n%s\n\n"
            "Return JSON with qualified, score, service_fit, need_summary, reasoning, risks, "
            "recommended_angle, evidence_quotes. evidence_quotes must be exact substrings of the record."
        ) % (int(min_score), evidence)
        data = self._generate(prompt, QUALIFICATION_SCHEMA, max_output_tokens=1600)
        return normalize_qualification(data, min_score=min_score)

    def draft_outreach(self, lead: Dict[str, Any], sender_name: str = "", portfolio_url: str = "") -> Dict[str, Any]:
        evidence = _evidence_text(lead)
        if not evidence:
            raise ProviderError("gemini", "lead has no usable requirement evidence; refusing to draft")
        sender = sender_name or "the owner"
        prompt = (
            "Write a short, specific, non-pushy first-contact message to this business.\n"
            "Rules:\n"
            "- 90-170 words for email, 30-70 words for WhatsApp.\n"
            "- Reference the evidence shown, without quoting more than 20 words.\n"
            "- One clear question about scope and timing. No pricing, no guarantees, no fake familiarity.\n"
            "- No placeholders, brackets or template markers.\n"
            "- Sign as %s. Include the portfolio link %s in the email body if provided.\n\n"
            "LEAD RECORD (only source of truth):\n%s\n\n"
            "Return JSON with subject, email_body, whatsapp_body, personalization_notes."
        ) % (sender, portfolio_url or "(none)", evidence)
        data = self._generate(prompt, DRAFT_SCHEMA, max_output_tokens=1600)
        return normalize_draft(data)

    def draft_follow_up(
        self,
        lead: Dict[str, Any],
        previous_subject: str = "",
        sender_name: str = "",
        portfolio_url: str = "",
    ) -> Dict[str, Any]:
        """Short, polite follow-up that offers an easy exit. Never invents a reply."""
        evidence = _evidence_text(lead)
        if not evidence:
            raise ProviderError("gemini", "lead has no usable requirement evidence; refusing to draft")
        prompt = (
            "Write a single short follow-up email (60-120 words) about the requirement below.\n"
            "Rules:\n"
            "- Assume the first email may not have been read; do not claim they replied or were interested.\n"
            "- Restate the requirement in one sentence, ask one simple question, and offer an easy exit.\n"
            "- No pricing, no pressure, no placeholders.\n"
            "- Sign as %s. Include %s if provided.\n\n"
            "PREVIOUS SUBJECT (context only): %s\n\n"
            "LEAD RECORD (only source of truth):\n%s\n\n"
            "Return JSON with subject, email_body, whatsapp_body, personalization_notes."
        ) % (sender_name or "the owner", portfolio_url or "(none)", previous_subject or "(none)", evidence)
        data = self._generate(prompt, DRAFT_SCHEMA, max_output_tokens=1200)
        return normalize_draft(data)


# -------------------------------------------------------------------- parsing


def extract_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    chunks = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def parse_json_object(text: str) -> Dict[str, Any]:
    """Parse JSON even if the model wrapped it in a code fence or added prose."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\s*", "", clean)
        clean = re.sub(r"```$", "", clean).strip()
    try:
        parsed = json.loads(clean)
    except ValueError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("gemini", "response was not valid JSON") from None
        try:
            parsed = json.loads(clean[start : end + 1])
        except ValueError:
            raise ProviderError("gemini", "response was not valid JSON") from None
    if not isinstance(parsed, dict):
        raise ProviderError("gemini", "response JSON was not an object")
    return parsed


def normalize_qualification(data: Dict[str, Any], min_score: int = 70) -> Dict[str, Any]:
    try:
        score = int(float(data.get("score") or 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    explicit = bool(data.get("qualified"))
    qualified = explicit and score >= int(min_score)
    risks = data.get("risks") or []
    quotes = data.get("evidence_quotes") or []
    return {
        "qualified": qualified,
        "score": score,
        "service_fit": _clean_text(data.get("service_fit"), 160),
        "need_summary": _clean_text(data.get("need_summary"), 400),
        "reasoning": _clean_text(data.get("reasoning"), 700),
        "risks": [_clean_text(risk, 200) for risk in risks if str(risk).strip()][:6] if isinstance(risks, list) else [],
        "recommended_angle": _clean_text(data.get("recommended_angle"), 400),
        "evidence_quotes": [_clean_text(quote, 300) for quote in quotes if str(quote).strip()][:5] if isinstance(quotes, list) else [],
        "model": "gemini",
        "evaluated_at": now_iso(),
    }


def normalize_draft(data: Dict[str, Any]) -> Dict[str, Any]:
    draft = {
        "subject": _clean_text(data.get("subject"), 140),
        "email_body": str(data.get("email_body") or "").strip(),
        "whatsapp_body": str(data.get("whatsapp_body") or "").strip(),
        "personalization_notes": _clean_text(data.get("personalization_notes"), 300),
        "generated_at": now_iso(),
    }
    return draft


def validate_draft(draft: Dict[str, Any], portfolio_url: str = "") -> List[str]:
    """Return a list of blocking problems. An empty list means the draft is usable."""
    problems: List[str] = []
    email_body = str(draft.get("email_body") or "").strip()
    subject = str(draft.get("subject") or "").strip()
    if not subject:
        problems.append("Email subject is empty.")
    if len(email_body) < 80:
        problems.append("Email body is too short to be a genuine personalized message.")
    if len(email_body) > 2600:
        problems.append("Email body is too long.")
    lowered = (subject + "\n" + email_body).lower()
    for marker in BANNED_DRAFT_MARKERS:
        if marker in lowered:
            problems.append(f"Draft contains a placeholder marker: {marker!r}.")
    if "unsubscribe" in lowered:
        problems.append("Do not rely on an unsubscribe line as consent evidence; review the draft manually.")
    if portfolio_url and portfolio_url not in email_body:
        problems.append("Email body must include the configured portfolio URL.")
    whatsapp_body = str(draft.get("whatsapp_body") or "").strip()
    if whatsapp_body and len(whatsapp_body) > 900:
        problems.append("WhatsApp body is too long; keep it under 900 characters.")
    return problems


def _evidence_text(lead: Dict[str, Any]) -> str:
    from ..qualify import requirement_evidence

    if not requirement_evidence(lead):
        return ""
    fields = [
        ("company", lead.get("company_name")),
        ("website", lead.get("website")),
        ("country", lead.get("country")),
        ("industry", lead.get("industry")),
        ("employee_range", lead.get("employee_range")),
        ("contact_name", lead.get("contact_name")),
        ("contact_title", lead.get("contact_title")),
        ("service_fit", lead.get("service_fit")),
        ("need_summary", lead.get("need_summary")),
        ("qualification_reason", lead.get("qualification_reason")),
        ("evidence", lead.get("notes")),
        ("source_url", lead.get("source_url")),
        ("source_provider", lead.get("source_provider")),
    ]
    return "\n".join(f"{name}: {str(value).strip()}" for name, value in fields if str(value or "").strip())


def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def client_from_config(config: Config, transport: Optional[Transport] = None) -> GeminiClient:
    return GeminiClient(
        config.gemini_api_key,
        model=config.gemini_model,
        base_url=config.gemini_base_url,
        transport=transport,
    )
