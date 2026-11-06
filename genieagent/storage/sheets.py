"""Google Sheets as the primary database.

Authentication options (all read from environment variables):

1. OAuth refresh token  - dependency-free, recommended on Termux.
2. Short-lived access token - useful for one-off manual runs.
3. Service account JSON - requires the optional ``google-auth`` package and is
   the usual choice for GitHub Actions.

Writes are read-merge-write with the header row preserved, so columns an owner
adds by hand in the spreadsheet are not destroyed.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Config, ConfigError
from ..http import ProviderError, Response, Transport, request, require_ok
from ..models import ACTIVITY_COLUMNS, LEAD_COLUMNS, OUTREACH_COLUMNS
from ..util import chunked, now_iso

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
TOKEN_URL = "https://oauth2.googleapis.com/token"
WRITE_CHUNK_ROWS = 500


def column_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    if index < 1:
        raise ValueError("Column index starts at 1")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def quote_range(tab: str, a1: str) -> str:
    safe_tab = tab.replace("'", "''")
    return f"'{safe_tab}'!{a1}"


# ------------------------------------------------------------------------ auth


class GoogleAuth:
    """Base token provider. ``token()`` must return a bearer token."""

    def token(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def refresh(self) -> None:
        return None


class StaticTokenAuth(GoogleAuth):
    def __init__(self, token: str) -> None:
        self._token = (token or "").strip()

    def token(self) -> str:
        if not self._token:
            raise ConfigError("GOOGLE_SHEETS_ACCESS_TOKEN is empty.")
        return self._token


class RefreshTokenAuth(GoogleAuth):
    """Exchanges a long-lived refresh token for access tokens (no third-party deps)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        transport: Optional[Transport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.transport = transport
        self.sleep = sleep
        self._token = ""
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        response = request(
            "POST",
            TOKEN_URL,
            provider="google_oauth",
            form_body={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            retries=2,
            transport=self.transport,
            sleep=self.sleep,
        )
        payload = require_ok(response, "google_oauth", "refresh access token")
        token = str(payload.get("access_token") or "")
        if not token:
            raise ProviderError("google_oauth", "token response did not include access_token")
        self._token = token
        self._expires_at = time.time() + float(payload.get("expires_in") or 3600)
        return token


class ServiceAccountAuth(GoogleAuth):
    """Service-account auth using the optional ``google-auth`` package."""

    def __init__(self, service_account_json: str, scopes: Sequence[str]) -> None:
        self._raw = service_account_json
        self._scopes = list(scopes)
        self._credentials: Any = None

    def _load(self) -> Any:
        if self._credentials is not None:
            return self._credentials
        try:
            from google.oauth2 import service_account  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore
        except ImportError:
            raise ConfigError(
                "GOOGLE_SERVICE_ACCOUNT_JSON requires the optional google-auth package. "
                "On Termux use GOOGLE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN instead (no extra packages)."
            ) from None
        raw = self._raw.strip()
        info = json.loads(Path(raw).read_text(encoding="utf-8")) if raw.startswith("/") or raw.endswith(".json") else json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=self._scopes)
        credentials.refresh(Request())
        self._credentials = credentials
        return credentials

    def token(self) -> str:
        credentials = self._load()
        if not credentials.valid:
            from google.auth.transport.requests import Request  # type: ignore

            credentials.refresh(Request())
        return str(credentials.token)


def build_auth(config: Config, transport: Optional[Transport] = None) -> GoogleAuth:
    mode = config.sheets_auth_mode
    if mode == "service_account":
        return ServiceAccountAuth(
            config.google_service_account_json,
            ["https://www.googleapis.com/auth/spreadsheets"],
        )
    if mode == "oauth_refresh_token":
        return RefreshTokenAuth(
            config.google_client_id, config.google_client_secret, config.google_refresh_token, transport=transport
        )
    if mode == "access_token":
        return StaticTokenAuth(config.google_access_token)
    raise ConfigError(
        "Google Sheets is not configured. Set GOOGLE_SHEETS_ID plus GOOGLE_OAUTH_CLIENT_ID, "
        "GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REFRESH_TOKEN (or a service account). "
        "See docs/GOOGLE_SHEETS_SETUP.md."
    )


# ------------------------------------------------------------------------- API


class GoogleSheetsAPI:
    def __init__(self, spreadsheet_id: str, auth: GoogleAuth, transport: Optional[Transport] = None) -> None:
        if not spreadsheet_id:
            raise ConfigError("GOOGLE_SHEETS_ID is required.")
        self.spreadsheet_id = spreadsheet_id
        self.auth = auth
        self.transport = transport

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.auth.token()}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Optional[Any] = None) -> Dict[str, Any]:
        url = f"{SHEETS_API}/{self.spreadsheet_id}{path}"
        response: Response = request(
            method,
            url,
            provider="google_sheets",
            headers=self._headers(),
            params=params,
            json_body=body,
            retries=3,
            transport=self.transport,
        )
        payload = require_ok(response, "google_sheets", f"{method} {path.split('?')[0]}")
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------ reads

    def values_get(self, tab: str, a1: str = "A1:ZZ20000") -> List[List[str]]:
        payload = self._call("GET", f"/values/{urllib.parse.quote(quote_range(tab, a1), safe='')}", params={"majorDimension": "ROWS"})
        values = payload.get("values") or []
        return [[str(cell) for cell in row] for row in values]

    def sheet_titles(self) -> List[str]:
        payload = self._call("GET", "", params={"fields": "sheets.properties.title"})
        return [sheet.get("properties", {}).get("title", "") for sheet in payload.get("sheets", [])]

    def ensure_tab(self, tab: str) -> None:
        titles = self.sheet_titles()
        if tab in titles:
            return
        self._call(
            "POST",
            ":batchUpdate",
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        )

    # ----------------------------------------------------------------- writes

    def values_update(self, tab: str, a1: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
        return self._call(
            "PUT",
            f"/values/{urllib.parse.quote(quote_range(tab, a1), safe='')}",
            params={"valueInputOption": value_input_option},
            body={"majorDimension": "ROWS", "values": values},
        )

    def values_clear(self, tab: str, a1: str) -> Dict[str, Any]:
        return self._call("POST", f"/values/{urllib.parse.quote(quote_range(tab, a1), safe='')}:clear", body={})

    def values_append(self, tab: str, values: List[List[Any]]) -> Dict[str, Any]:
        return self._call(
            "POST",
            f"/values/{urllib.parse.quote(quote_range(tab, 'A1'), safe='')}:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            body={"majorDimension": "ROWS", "values": values},
        )


# ----------------------------------------------------------------------- table


class SheetsTable:
    """Header-driven table with merge-on-write semantics."""

    def __init__(self, api: GoogleSheetsAPI, tab: str, columns: Sequence[str], key: str) -> None:
        self.api = api
        self.tab = tab
        self.columns = list(columns)
        self.key = key

    # ------------------------------------------------------------------ reading

    def load(self) -> Tuple[List[str], List[Dict[str, str]]]:
        raw = self.api.values_get(self.tab)
        if not raw:
            return [], []
        headers = [str(cell).strip() for cell in raw[0]]
        while headers and not headers[-1]:
            headers.pop()
        rows: List[Dict[str, str]] = []
        for values in raw[1:]:
            if not any(str(cell).strip() for cell in values):
                continue
            record: Dict[str, str] = {}
            for index, header in enumerate(headers):
                if not header:
                    continue
                record[header] = str(values[index]) if index < len(values) else ""
            rows.append(record)
        return headers, rows

    def ensure_headers(self) -> List[str]:
        headers, _ = self.load()
        if not headers:
            self.api.ensure_tab(self.tab)
            self.api.values_update(self.tab, "A1", [self.columns])
            return list(self.columns)
        missing = [column for column in self.columns if column not in headers]
        if missing:
            headers = headers + missing
            self.api.values_update(self.tab, "A1", [headers])
        return headers

    # ------------------------------------------------------------------ writing

    def write(self, headers: Sequence[str], rows: Iterable[Dict[str, Any]]) -> int:
        header_list = list(headers)
        matrix: List[List[str]] = [header_list]
        materialized = [row for row in rows]
        for row in materialized:
            matrix.append(["" if row.get(header) is None else str(row.get(header)) for header in header_list])
        # Remove stale trailing rows before writing the current dataset.
        existing = self.api.values_get(self.tab)
        last_column = column_letter(len(header_list))
        if len(existing) > len(matrix):
            self.api.values_clear(self.tab, f"A{len(matrix) + 1}:{last_column}{len(existing)}")
        for start in range(0, len(matrix), WRITE_CHUNK_ROWS):
            block = matrix[start : start + WRITE_CHUNK_ROWS]
            first_row = start + 1
            last_row = start + len(block)
            self.api.values_update(self.tab, f"A{first_row}:{last_column}{last_row}", block)
        return len(materialized)

    def upsert(self, incoming: Iterable[Dict[str, Any]], touch: bool = True) -> Dict[str, int]:
        headers, rows = self.load()
        if not headers:
            headers = self.ensure_headers()
        else:
            missing = [column for column in self.columns if column not in headers]
            if missing:
                headers = headers + missing
                self.api.values_update(self.tab, "A1", [headers])
        index = {str(row.get(self.key, "")): row for row in rows if row.get(self.key)}
        inserted = updated = unchanged = 0
        for item in incoming:
            record = dict(item)
            key_value = str(record.get(self.key, "") or "")
            if not key_value:
                continue
            if touch:
                record.setdefault("updated_at", now_iso())
            record.setdefault("created_at", record.get("updated_at") or now_iso())
            current = index.get(key_value)
            if current is None:
                new_row: Dict[str, str] = {header: "" for header in headers}
                for column, value in record.items():
                    new_row[column] = "" if value is None else str(value)
                rows.append(new_row)
                index[key_value] = new_row
                inserted += 1
                continue
            before = dict(current)
            for column, value in record.items():
                if column == "created_at" and str(current.get(column) or "").strip():
                    continue
                if value is None:
                    continue
                current[column] = str(value)
            if {k: current.get(k) for k in before} == before:
                unchanged += 1
            else:
                updated += 1
        self.write(headers, rows)
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged, "total": len(rows)}

    def update(self, key_value: str, **fields: Any) -> Optional[Dict[str, str]]:
        headers, rows = self.load()
        target = None
        for row in rows:
            if str(row.get(self.key, "")) == str(key_value):
                for column, value in fields.items():
                    row[column] = "" if value is None else str(value)
                row["updated_at"] = now_iso()
                target = row
                break
        if target is None:
            return None
        if not headers:
            headers = self.ensure_headers()
        self.write(headers, rows)
        return target


# ------------------------------------------------------------------ factories


def sheets_table(config: Config, tab: str, columns: Sequence[str], key: str, transport: Optional[Transport] = None) -> SheetsTable:
    api = GoogleSheetsAPI(config.sheets_id, build_auth(config, transport=transport), transport=transport)
    return SheetsTable(api, tab, columns, key)


def leads_sheet(config: Config, transport: Optional[Transport] = None) -> SheetsTable:
    return sheets_table(config, config.sheets_leads_tab, LEAD_COLUMNS, "lead_id", transport=transport)


def outreach_sheet(config: Config, transport: Optional[Transport] = None) -> SheetsTable:
    return sheets_table(config, config.sheets_outreach_tab, OUTREACH_COLUMNS, "draft_id", transport=transport)


def activity_sheet(config: Config, transport: Optional[Transport] = None) -> SheetsTable:
    return sheets_table(config, config.sheets_activity_tab, ACTIVITY_COLUMNS, "event_id", transport=transport)
