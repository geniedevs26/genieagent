"""Small shared helpers: time, CSV/JSON persistence, masking and IDs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# --------------------------------------------------------------------------- time


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """ISO-8601 UTC timestamp with a trailing Z (stable in CSV and Sheets)."""
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return now_utc().date().isoformat()


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def days_since(value: Any) -> Optional[float]:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    return (now_utc() - parsed).total_seconds() / 86400.0


# -------------------------------------------------------------------------- IDs


def stable_id(*parts: str) -> str:
    """Deterministic UUID-like identifier so re-runs never duplicate records."""
    digest = hashlib.sha256("|".join(str(p or "").strip().lower() for p in parts).encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ----------------------------------------------------------------------- masking


def mask_email(value: Any) -> str:
    """Mask an address for dashboards and logs. Never reveal the full mailbox."""
    text = str(value or "").strip()
    if not text or "@" not in text:
        return ""
    local, _, domain = text.partition("@")
    keep = local[:1] if local else ""
    return f"{keep}{'*' * max(2, min(6, len(local) - 1))}@{domain}"


def mask_phone(value: Any) -> str:
    """Mask a phone number. Only the last two digits survive."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 4:
        return "hidden" if digits else ""
    return "*" * (len(digits) - 2) + digits[-2:]


def mask_recipient(channel: str, value: Any) -> str:
    if channel == "whatsapp":
        return mask_phone(value)
    return mask_email(value)


# ------------------------------------------------------------------------ files


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never truncates a data file."""
    ensure_dir(path.parent)
    handle = tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), prefix=path.name + ".", suffix=".tmp", encoding="utf-8", newline=""
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], columns: List[str]) -> None:
    ensure_dir(path.parent)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _csv_value(row.get(column)) for column in columns})
    atomic_write(path, stream.getvalue())


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def chunked(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + size]
