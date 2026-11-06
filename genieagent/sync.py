"""Google Sheets <-> leads.csv synchronisation (Sheets is the primary database)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import Config
from .http import Transport
from .models import ACTIVITY_COLUMNS, LEAD_COLUMNS, OUTREACH_COLUMNS
from .normalize import dedupe_leads
from .storage.csv_store import activity_table, leads_table, outreach_table
from .storage.sheets import activity_sheet, leads_sheet, outreach_sheet
from .util import now_iso


def merge_outreach(sheet_row: Dict[str, Any], local_row: Dict[str, Any]) -> Dict[str, Any]:
    """Sheets holds owner approvals; local holds send results. Merge without losing either."""
    merged = dict(sheet_row)
    for column, value in local_row.items():
        text = "" if value is None else str(value)
        if not text:
            continue
        if not str(merged.get(column) or "").strip():
            merged[column] = text
        elif column in {"sent_at", "provider_message_id", "delivery_status", "failure_reason", "attempt_count", "updated_at"}:
            # Newest write wins for delivery facts.
            if str(merged.get(column) or "") <= text and column != "updated_at":
                merged[column] = text
            elif column == "updated_at" and text > str(merged.get(column) or ""):
                merged[column] = text
    return merged


def _merge_leads(sheet_rows: List[Dict[str, Any]], local_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    combined = dedupe_leads(list(sheet_rows) + list(local_rows))[0]
    return combined


def sync_leads(config: Config, direction: str = "both", transport: Optional[Transport] = None) -> Dict[str, Any]:
    local = leads_table(config.leads_csv)
    local_rows = local.load()
    if direction == "push" and not config.sheets_ready:
        return {"skipped": "Google Sheets is not configured; leads.csv was kept.", "local": len(local_rows)}
    sheet = leads_sheet(config, transport=transport)
    sheet_rows = [] if direction == "push" else _safe_sheet_load(sheet, config)
    if direction == "pull":
        merged = sheet_rows
        local.upsert(merged)
    elif direction == "push":
        merged = local_rows
        sheet.upsert(merged)
    else:
        merged = _merge_leads(sheet_rows, local_rows)
        local.save(merged)
        sheet.upsert(merged)
    return {
        "direction": direction,
        "rows": len(merged),
        "sheet_rows_before": len(sheet_rows),
        "local_rows_before": len(local_rows),
        "timestamp": now_iso(),
    }


def sync_outreach(config: Config, direction: str = "both", transport: Optional[Transport] = None) -> Dict[str, Any]:
    local = outreach_table(config.outreach_csv)
    local_rows = local.load()
    if direction == "push" and not config.sheets_ready:
        return {"skipped": "Google Sheets is not configured; outreach.csv was kept.", "local": len(local_rows)}
    sheet = outreach_sheet(config, transport=transport)
    sheet_rows = [] if direction == "push" else _safe_sheet_load(sheet, config)
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in sheet_rows:
        key = str(row.get("draft_id") or "")
        if key:
            by_key[key] = row
    for row in local_rows:
        key = str(row.get("draft_id") or "")
        if not key:
            continue
        by_key[key] = merge_outreach(by_key[key], row) if key in by_key else row
    merged = list(by_key.values())
    if direction in {"both", "pull"}:
        local.save(merged)
    if direction in {"both", "push"}:
        sheet.upsert(merged)
    return {
        "direction": direction,
        "rows": len(merged),
        "sheet_rows_before": len(sheet_rows),
        "local_rows_before": len(local_rows),
        "timestamp": now_iso(),
    }


def sync_activity(config: Config, transport: Optional[Transport] = None) -> Dict[str, Any]:
    local = activity_table(config.activity_csv)
    rows = local.load()
    if not config.sheets_ready or not rows:
        return {"pushed": 0, "local": len(rows)}
    sheet = activity_sheet(config, transport=transport)
    result = sheet.upsert(rows, touch=False)
    return {"pushed": result.get("inserted", 0) + result.get("updated", 0), "local": len(rows)}


def _safe_sheet_load(sheet: Any, config: Config) -> List[Dict[str, Any]]:
    """Read a sheet, tolerating a brand-new spreadsheet with no tabs yet."""
    try:
        headers, rows = sheet.load()
    except Exception:
        if not config.sheets_id:
            return []
        sheet.api.ensure_tab(sheet.tab)
        headers, rows = sheet.load()
    return rows


def sync_all(config: Config, direction: str = "both", transport: Optional[Transport] = None) -> Dict[str, Any]:
    if direction not in {"both", "pull", "push"}:
        raise ValueError("direction must be both, pull or push")
    report: Dict[str, Any] = {"direction": direction}
    report["leads"] = sync_leads(config, direction, transport)
    report["outreach"] = sync_outreach(config, direction, transport)
    report["activity"] = sync_activity(config, transport)
    return report


def schema_summary() -> Dict[str, Sequence[str]]:
    return {"leads": LEAD_COLUMNS, "outreach": OUTREACH_COLUMNS, "activity": ACTIVITY_COLUMNS}
