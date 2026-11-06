"""Storage adapters: leads.csv (local/backup) and Google Sheets (primary database)."""

from .csv_store import CsvTable, FileLock  # noqa: F401
