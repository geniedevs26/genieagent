"""Local CSV tables: leads.csv is the portable backup and Termux-friendly store."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from ..models import ACTIVITY_COLUMNS, LEAD_COLUMNS, OUTREACH_COLUMNS
from ..normalize import dedupe_leads
from ..util import now_iso, read_csv, stable_id, write_csv


class FileLockError(RuntimeError):
    pass


@contextmanager
def FileLock(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Cross-process lock so a Termux run and an Actions run cannot interleave writes."""
    lock_path = Path(str(path) + ".lock")
    deadline = time.time() + timeout
    handle = None
    while True:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii"))
            break
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if time.time() >= deadline:
                raise FileLockError(f"Timed out waiting for lock {lock_path}. Another GenieAgent run is active.")
            time.sleep(0.2)
    try:
        yield
    finally:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass
            try:
                lock_path.unlink()
            except OSError:
                pass


class CsvTable:
    """A schema-aware CSV table with idempotent upserts."""

    def __init__(self, path: Path, columns: Sequence[str], key: str, dedupe: bool = False) -> None:
        self.path = Path(path)
        self.columns = list(columns)
        self.key = key
        self.dedupe = dedupe

    # ------------------------------------------------------------------ loading

    def load(self) -> List[Dict[str, str]]:
        rows = read_csv(self.path)
        cleaned: List[Dict[str, str]] = []
        for row in rows:
            if not any(str(value or "").strip() for value in row.values()):
                continue
            record = {column: str(row.get(column, "") or "") for column in self.columns}
            # Preserve columns an operator added by hand in the CSV.
            for extra_key, extra_value in row.items():
                if extra_key not in record:
                    record[extra_key] = str(extra_value or "")
            cleaned.append(record)
        return cleaned

    def save(self, rows: Iterable[Dict[str, Any]]) -> None:
        materialized: List[Dict[str, Any]] = []
        extra_columns: List[str] = []
        for row in rows:
            record = {column: row.get(column, "") for column in self.columns}
            for extra_key, extra_value in row.items():
                if extra_key not in record:
                    record[extra_key] = extra_value
                    if extra_key not in extra_columns:
                        extra_columns.append(extra_key)
            materialized.append(record)
        write_csv(self.path, materialized, self.columns + extra_columns)

    # ------------------------------------------------------------------- writing

    def upsert(self, incoming: Iterable[Dict[str, Any]], touch: bool = True) -> Dict[str, int]:
        """Insert or merge records by key. Returns counts for reporting."""
        rows = self.load()
        index = {str(row.get(self.key, "")): row for row in rows if row.get(self.key)}
        inserted = updated = unchanged = 0
        for item in incoming:
            record = dict(item)
            if self.key == "lead_id" and not record.get("lead_id"):
                record["lead_id"] = stable_id(
                    record.get("domain") or record.get("website") or record.get("company_name") or "",
                )
            if self.key == "event_id" and not record.get("event_id"):
                record["event_id"] = stable_id(now_iso(), record.get("event_type", ""), record.get("summary", ""))
            key_value = str(record.get(self.key, "") or "")
            if not key_value:
                continue
            if touch:
                record.setdefault("updated_at", now_iso())
            record.setdefault("created_at", record.get("updated_at") or now_iso())
            current = index.get(key_value)
            if current is None:
                merged = {column: record.get(column, "") for column in self.columns}
                for extra_key, extra_value in record.items():
                    if extra_key not in merged:
                        merged[extra_key] = extra_value
                rows.append(merged)
                index[key_value] = merged
                inserted += 1
                continue
            before = dict(current)
            for column, value in record.items():
                if column == "created_at" and str(current.get(column) or "").strip():
                    continue
                if value is None:
                    continue
                current[column] = value
            if {k: current.get(k) for k in before} == before:
                unchanged += 1
            else:
                updated += 1
        if self.dedupe:
            unique, removed = dedupe_leads(rows)
            rows = unique
            if removed:
                inserted = max(0, inserted - removed)
        self.save(rows)
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged, "total": len(rows)}

    def update(self, key_value: str, **fields: Any) -> Optional[Dict[str, str]]:
        rows = self.load()
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
        self.save(rows)
        return target

    def find(self, **criteria: Any) -> List[Dict[str, str]]:
        rows = self.load()
        matches = []
        for row in rows:
            if all(str(row.get(key, "")) == str(value) for key, value in criteria.items()):
                matches.append(row)
        return matches

    def get(self, key_value: str) -> Optional[Dict[str, str]]:
        for row in self.load():
            if str(row.get(self.key, "")) == str(key_value):
                return row
        return None


def leads_table(path: Path) -> CsvTable:
    return CsvTable(path, LEAD_COLUMNS, "lead_id", dedupe=True)


def outreach_table(path: Path) -> CsvTable:
    return CsvTable(path, OUTREACH_COLUMNS, "draft_id")


def activity_table(path: Path) -> CsvTable:
    return CsvTable(path, ACTIVITY_COLUMNS, "event_id")


def log_activity(path: Path, event_type: str, status: str, summary: str, details: Any = "", lead_id: str = "") -> Dict[str, str]:
    """Append an audit event. Detail is JSON so failures stay diagnosable."""
    import json

    table = activity_table(path)
    record = {
        "event_id": stable_id(now_iso(), event_type, summary, lead_id),
        "timestamp": now_iso(),
        "event_type": event_type,
        "status": status,
        "lead_id": lead_id,
        "summary": summary[:900],
        "details": json.dumps(details, ensure_ascii=False) if not isinstance(details, str) else details,
    }
    table.upsert([record], touch=False)
    return record
