"""Environment-driven configuration with conservative safety defaults.

Every credential is read from the environment (Termux ``.env`` or GitHub
Secrets). Nothing in this module writes, prints or logs a secret value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

DEFAULT_DATA_DIR = Path("data")
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"  # current stable Flash model (Sept 2026)
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_APOLLO_BASE = "https://api.apollo.io/api/v1"
DEFAULT_HUNTER_BASE = "https://api.hunter.io/v2"
DEFAULT_BREVO_HOST = "smtp-relay.brevo.com"
DEFAULT_BREVO_PORT = 587
DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_GREEN_BASE = "https://api.green-api.com"


class ConfigError(RuntimeError):
    """Raised when an environment variable is present but invalid."""


def load_env_file(path: Path = Path(".env"), env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Load KEY=VALUE pairs from a dotenv file without overriding real env vars.

    Values are never echoed. Quotes around values are stripped. Malformed lines
    are ignored rather than guessed at.
    """
    target = dict(os.environ if env is None else env)
    if not path.exists():
        return target
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return target
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key or key in target:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        target[key] = value
    return target


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    return str(env.get(name, default) or "").strip()


def _flag(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on", "y"}:
        return True
    if value in {"0", "false", "no", "off", "n"}:
        return False
    raise ConfigError(f"{name} must be true/false (or 1/0); refusing to guess.")


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 0, maximum: int = 100000) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ConfigError(f"{name} must be an integer.") from None
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _float(env: Mapping[str, str], name: str, default: float, minimum: float = 0.0, maximum: float = 600.0) -> float:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        raise ConfigError(f"{name} must be a number.") from None
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _csv_list(env: Mapping[str, str], name: str, default: Iterable[str] = ()) -> Tuple[str, ...]:
    raw = env.get(name)
    if raw is None:
        return tuple(default)
    items = [item.strip() for item in str(raw).split(",")]
    return tuple(item for item in items if item)


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    env_name: str = "local"

    # paths
    data_dir: Path = DEFAULT_DATA_DIR
    leads_csv: Path = DEFAULT_DATA_DIR / "leads.csv"
    outreach_csv: Path = DEFAULT_DATA_DIR / "outreach.csv"
    activity_csv: Path = DEFAULT_DATA_DIR / "activity.csv"
    dashboard_json: Path = DEFAULT_DATA_DIR / "dashboard.json"

    # behaviour
    dry_run: bool = False
    log_level: str = "INFO"
    max_leads_per_run: int = 50
    request_timeout: int = 45
    request_pause: float = 1.0

    # apollo
    apollo_api_key: str = ""
    apollo_base_url: str = DEFAULT_APOLLO_BASE
    apollo_keyword_tags: Tuple[str, ...] = ()
    apollo_locations: Tuple[str, ...] = ()
    apollo_employee_ranges: Tuple[str, ...] = ()
    apollo_pages: int = 1
    apollo_per_page: int = 25

    # hunter
    hunter_api_key: str = ""
    hunter_base_url: str = DEFAULT_HUNTER_BASE
    hunter_domain_limit: int = 10

    # gemini
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_base_url: str = DEFAULT_GEMINI_BASE

    # google sheets
    sheets_id: str = ""
    sheets_leads_tab: str = "Leads"
    sheets_outreach_tab: str = "Outreach"
    sheets_activity_tab: str = "Activity"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_access_token: str = ""
    google_service_account_json: str = ""

    # sender identity
    owner_email: str = ""
    owner_name: str = ""
    portfolio_url: str = ""

    # outreach safety
    outreach_send_enabled: bool = False
    auto_outreach_enabled: bool = False
    outreach_daily_limit: int = 10
    outreach_min_score: int = 70
    outreach_followup_days: Tuple[int, ...] = (5, 12, 21)
    suppressed_emails: Tuple[str, ...] = ()

    # brevo smtp
    brevo_smtp_host: str = DEFAULT_BREVO_HOST
    brevo_smtp_port: int = DEFAULT_BREVO_PORT
    brevo_smtp_login: str = ""
    brevo_smtp_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = ""
    brevo_api_key: str = ""

    # whatsapp
    whatsapp_provider: str = "none"
    whatsapp_send_enabled: bool = False
    whatsapp_meta_phone_number_id: str = ""
    whatsapp_meta_token: str = ""
    whatsapp_graph_version: str = DEFAULT_GRAPH_VERSION
    whatsapp_meta_template_name: str = ""
    whatsapp_meta_template_lang: str = "en_US"
    green_api_id_instance: str = ""
    green_api_token: str = ""
    green_api_base_url: str = DEFAULT_GREEN_BASE

    extra: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, dotenv_path: Optional[Path] = Path(".env")) -> "Config":
        source: Dict[str, str] = dict(env) if env is not None else load_env_file(dotenv_path or Path(".env"))
        data_dir = Path(_text(source, "GENIE_DATA_DIR", str(DEFAULT_DATA_DIR)) or DEFAULT_DATA_DIR)
        provider = _text(source, "WHATSAPP_PROVIDER", "none").lower() or "none"
        if provider in {"meta", "cloud", "meta_cloud", "whatsapp_cloud"}:
            provider = "meta_cloud"
        if provider in {"green", "greenapi", "green_api", "green-api"}:
            provider = "green_api"
        if provider in {"", "off", "disabled"}:
            provider = "none"
        if provider not in {"none", "meta_cloud", "green_api"}:
            raise ConfigError("WHATSAPP_PROVIDER must be none, meta_cloud or green_api.")
        return cls(
            env_name=_text(source, "GENIE_ENV", "local") or "local",
            data_dir=data_dir,
            leads_csv=Path(_text(source, "GENIE_LEADS_CSV", str(data_dir / "leads.csv"))),
            outreach_csv=Path(_text(source, "GENIE_OUTREACH_CSV", str(data_dir / "outreach.csv"))),
            activity_csv=Path(_text(source, "GENIE_ACTIVITY_CSV", str(data_dir / "activity.csv"))),
            dashboard_json=Path(_text(source, "GENIE_DASHBOARD_JSON", str(data_dir / "dashboard.json"))),
            dry_run=_flag(source, "GENIE_DRY_RUN", False),
            log_level=_text(source, "GENIE_LOG_LEVEL", "INFO").upper(),
            max_leads_per_run=_int(source, "GENIE_MAX_LEADS_PER_RUN", 50, 1, 1000),
            request_timeout=_int(source, "GENIE_HTTP_TIMEOUT", 45, 5, 300),
            request_pause=_float(source, "GENIE_REQUEST_PAUSE", 1.0, 0.0, 120.0),
            apollo_api_key=_text(source, "APOLLO_API_KEY"),
            apollo_base_url=_text(source, "APOLLO_BASE_URL", DEFAULT_APOLLO_BASE),
            apollo_keyword_tags=_csv_list(source, "APOLLO_KEYWORD_TAGS"),
            apollo_locations=_csv_list(source, "APOLLO_LOCATIONS"),
            apollo_employee_ranges=_csv_list(source, "APOLLO_EMPLOYEE_RANGES"),
            apollo_pages=_int(source, "APOLLO_PAGES", 1, 1, 50),
            apollo_per_page=_int(source, "APOLLO_PER_PAGE", 25, 1, 100),
            hunter_api_key=_text(source, "HUNTER_API_KEY"),
            hunter_base_url=_text(source, "HUNTER_BASE_URL", DEFAULT_HUNTER_BASE),
            hunter_domain_limit=_int(source, "HUNTER_DOMAIN_LIMIT", 10, 1, 100),
            gemini_api_key=_text(source, "GEMINI_API_KEY"),
            gemini_model=_text(source, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            gemini_base_url=_text(source, "GEMINI_BASE_URL", DEFAULT_GEMINI_BASE),
            sheets_id=_text(source, "GOOGLE_SHEETS_ID"),
            sheets_leads_tab=_text(source, "GOOGLE_SHEETS_LEADS_TAB", "Leads"),
            sheets_outreach_tab=_text(source, "GOOGLE_SHEETS_OUTREACH_TAB", "Outreach"),
            sheets_activity_tab=_text(source, "GOOGLE_SHEETS_ACTIVITY_TAB", "Activity"),
            google_client_id=_text(source, "GOOGLE_OAUTH_CLIENT_ID"),
            google_client_secret=_text(source, "GOOGLE_OAUTH_CLIENT_SECRET"),
            google_refresh_token=_text(source, "GOOGLE_OAUTH_REFRESH_TOKEN"),
            google_access_token=_text(source, "GOOGLE_SHEETS_ACCESS_TOKEN"),
            google_service_account_json=_text(source, "GOOGLE_SERVICE_ACCOUNT_JSON"),
            owner_email=_text(source, "GENIE_OWNER_EMAIL"),
            owner_name=_text(source, "GENIE_OWNER_NAME", "GenieDevs"),
            portfolio_url=_text(source, "GENIE_PORTFOLIO_URL"),
            outreach_send_enabled=_flag(source, "OUTREACH_SEND_ENABLED", False),
            auto_outreach_enabled=_flag(source, "AUTO_OUTREACH_ENABLED", False),
            outreach_daily_limit=_int(source, "OUTREACH_DAILY_LIMIT", 10, 1, 200),
            outreach_min_score=_int(source, "OUTREACH_MIN_SCORE", 70, 1, 100),
            outreach_followup_days=tuple(
                int(value)
                for value in _csv_list(source, "OUTREACH_FOLLOWUP_DAYS", ("5", "12", "21"))
                if str(value).isdigit()
            )
            or (5, 12, 21),
            suppressed_emails=tuple(
                item.lower() for item in _csv_list(source, "SUPPRESSED_EMAILS")
            ),
            brevo_smtp_host=_text(source, "BREVO_SMTP_HOST", DEFAULT_BREVO_HOST),
            brevo_smtp_port=_int(source, "BREVO_SMTP_PORT", DEFAULT_BREVO_PORT, 1, 65535),
            brevo_smtp_login=_text(source, "BREVO_SMTP_LOGIN"),
            brevo_smtp_key=_text(source, "BREVO_SMTP_KEY"),
            brevo_sender_email=_text(source, "BREVO_SENDER_EMAIL"),
            brevo_sender_name=_text(source, "BREVO_SENDER_NAME"),
            brevo_api_key=_text(source, "BREVO_API_KEY"),
            whatsapp_provider=provider,
            whatsapp_send_enabled=_flag(source, "WHATSAPP_SEND_ENABLED", False),
            whatsapp_meta_phone_number_id=_text(source, "WHATSAPP_PHONE_NUMBER_ID"),
            whatsapp_meta_token=_text(source, "WHATSAPP_ACCESS_TOKEN"),
            whatsapp_graph_version=_text(source, "WHATSAPP_GRAPH_VERSION", DEFAULT_GRAPH_VERSION),
            whatsapp_meta_template_name=_text(source, "WHATSAPP_TEMPLATE_NAME"),
            whatsapp_meta_template_lang=_text(source, "WHATSAPP_TEMPLATE_LANG", "en_US"),
            green_api_id_instance=_text(source, "GREEN_API_ID_INSTANCE"),
            green_api_token=_text(source, "GREEN_API_TOKEN"),
            green_api_base_url=_text(source, "GREEN_API_BASE_URL", DEFAULT_GREEN_BASE),
        )

    # ------------------------------------------------------------- readiness

    @property
    def apollo_ready(self) -> bool:
        return bool(self.apollo_api_key)

    @property
    def hunter_ready(self) -> bool:
        return bool(self.hunter_api_key)

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def sheets_auth_mode(self) -> str:
        if self.google_service_account_json:
            return "service_account"
        if self.google_client_id and self.google_client_secret and self.google_refresh_token:
            return "oauth_refresh_token"
        if self.google_access_token:
            return "access_token"
        return "none"

    @property
    def sheets_ready(self) -> bool:
        return bool(self.sheets_id) and self.sheets_auth_mode != "none"

    @property
    def brevo_ready(self) -> bool:
        return bool(
            self.brevo_smtp_host
            and self.brevo_smtp_login
            and self.brevo_smtp_key
            and (self.brevo_sender_email or self.owner_email)
        )

    @property
    def whatsapp_ready(self) -> bool:
        if self.whatsapp_provider == "meta_cloud":
            return bool(self.whatsapp_meta_phone_number_id and self.whatsapp_meta_token)
        if self.whatsapp_provider == "green_api":
            return bool(self.green_api_id_instance and self.green_api_token)
        return False

    @property
    def email_sending_ready(self) -> bool:
        return self.brevo_ready and self.outreach_send_enabled

    @property
    def sender_email(self) -> str:
        return self.brevo_sender_email or self.owner_email

    def safety_summary(self) -> Dict[str, Any]:
        """Credential/config presence for dashboards. Never includes values."""
        return {
            "apollo_configured": self.apollo_ready,
            "hunter_configured": self.hunter_ready,
            "gemini_configured": self.gemini_ready,
            "gemini_model": self.gemini_model,
            "google_sheets_configured": self.sheets_ready,
            "google_sheets_auth_mode": self.sheets_auth_mode,
            "brevo_smtp_configured": self.brevo_ready,
            "whatsapp_provider": self.whatsapp_provider,
            "whatsapp_configured": self.whatsapp_ready,
            "outreach_send_enabled": self.outreach_send_enabled,
            "whatsapp_send_enabled": self.whatsapp_send_enabled,
            "auto_outreach_enabled": self.auto_outreach_enabled,
            "automatic_outreach": False,
            "owner_email_configured": bool(self.owner_email),
        }

    def secrets(self) -> List[str]:
        """Secret values to redact from any log or report."""
        return [
            self.apollo_api_key,
            self.hunter_api_key,
            self.gemini_api_key,
            self.google_client_secret,
            self.google_refresh_token,
            self.google_access_token,
            self.google_service_account_json,
            self.brevo_smtp_key,
            self.brevo_api_key,
            self.whatsapp_meta_token,
            self.green_api_token,
        ]


def ensure_supported_model(model: str) -> str:
    """Reject retired Gemini 1.x/2.0 models with a clear, actionable error.

    Gemini 1.5 Flash is shut down and 2.5 models are limited to existing users,
    so the project defaults to the current stable Flash model.
    """
    name = (model or "").strip()
    retired_prefixes = ("gemini-1.", "gemini-pro", "gemini-2.0", "gemini-2.5-pro", "gemini-2.5-flash")
    if not name:
        raise ConfigError("GEMINI_MODEL is empty; use gemini-3.8-flash.")
    if name.startswith(retired_prefixes):
        raise ConfigError(
            f"GEMINI_MODEL={name} is retired or restricted. Use gemini-3.8-flash "
            "(or gemini-3.5-flash-lite) and update GEMINI_MODEL."
        )
    return name
