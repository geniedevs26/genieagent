"""Minimal JSON HTTP client with retries, injectable transport and secret-safe errors.

Only the Python standard library is used so this module works on Termux and in
GitHub Actions without installing requests/urllib3.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

USER_AGENT = "GenieAgent/2.0 (+https://github.com/geniedevs26/genieagent)"

# A transport receives (method, url, headers, body_bytes) and returns
# (status_code, response_headers, response_text). Tests inject a fake transport.
Transport = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, Dict[str, str], str]]


class ProviderError(RuntimeError):
    """Raised for any provider failure. Messages never contain credentials."""

    def __init__(
        self,
        provider: str,
        message: str,
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
        body: str = "",
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.body = (body or "")[:2000]


@dataclass
class Response:
    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        try:
            return json.loads(self.text) if self.text.strip() else None
        except ValueError:
            return None


def _urllib_transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, Dict[str, str], str]:
    request = urllib.request.Request(url, data=body, method=method.upper())
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read().decode("utf-8", "replace")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, payload


def request(
    method: str,
    url: str,
    *,
    provider: str = "http",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    form_body: Optional[Dict[str, Any]] = None,
    timeout: int = 45,
    retries: int = 2,
    backoff: float = 1.5,
    max_backoff: float = 20.0,
    retry_statuses: Iterable[int] = (408, 425, 429, 500, 502, 503, 504),
    transport: Optional[Transport] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Response:
    """Perform one HTTP request with bounded retries on transient failures.

    Sending messages must pass ``retries=0``: a duplicate outbound message is
    worse than a failure the owner can retry deliberately.
    """
    send = transport or _urllib_transport
    final_url = url
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            final_url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    body: Optional[bytes] = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif form_body is not None:
        body = urllib.parse.urlencode(form_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    attempt = 0
    while True:
        attempt += 1
        try:
            status, response_headers, text = send(method, final_url, request_headers, body)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            if attempt > retries:
                raise ProviderError(provider, f"network error after {attempt} attempt(s): {type(exc).__name__}") from None
            sleep(min(max_backoff, backoff ** attempt))
            continue

        if status in retry_statuses and attempt <= retries:
            retry_after = _retry_after(response_headers)
            delay = retry_after if retry_after is not None else min(max_backoff, backoff ** attempt)
            sleep(min(max_backoff, max(0.0, delay)))
            continue
        return Response(status=status, headers=response_headers or {}, text=text or "")


def _retry_after(headers: Dict[str, str]) -> Optional[float]:
    for key in ("retry-after", "x-ratelimit-reset"):
        value = (headers or {}).get(key)
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def require_ok(response: Response, provider: str, action: str, body_limit: int = 600) -> Any:
    """Return parsed JSON or raise a ProviderError with a safe excerpt."""
    if not response.ok:
        raise ProviderError(
            provider,
            f"{action} failed with HTTP {response.status}: {_safe_excerpt(response.text, body_limit)}",
            status=response.status,
            body=response.text,
        )
    payload = response.json()
    if payload is None:
        raise ProviderError(provider, f"{action} returned a non-JSON response", status=response.status, body=response.text)
    return payload


def _safe_excerpt(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:limit]


def redact(text: Any, secrets: Iterable[str]) -> str:
    """Remove known secret values from a string before logging or reporting."""
    output = str(text or "")
    for secret in secrets:
        if secret and len(str(secret)) >= 6:
            output = output.replace(str(secret), "[redacted]")
    return output


def bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
