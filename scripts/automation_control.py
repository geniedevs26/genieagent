"""Fail-closed, database-backed outbound controls shared by GenieAgent workers."""
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://irpqaoooosrjhviwdddo.supabase.co").rstrip("/")
CHANNELS = ("email", "follow_up", "ai_reply", "client_stage_email")


class OutboundBlocked(RuntimeError):
    """Raised when the owner has not explicitly enabled this outbound channel."""


def read_rows(table, key, query):
    url = SUPABASE_URL + "/rest/v1/" + table + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", "replace")
            value = json.loads(raw) if raw.strip() else []
            if not isinstance(value, list):
                raise OutboundBlocked("Automation controls returned an invalid response.")
            return value
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        # Missing migration, API failure, timeout or malformed response must never enable sending.
        raise OutboundBlocked("Outbound blocked: central controls are unavailable; fail-closed.") from exc


def assert_outbound_enabled(key, owner_id, channel, recipient=None):
    if not key or not owner_id or channel not in CHANNELS:
        raise OutboundBlocked("Outbound blocked: missing identity or unknown channel.")
    controls = read_rows("automation_controls", key, {
        "owner_id": "eq." + owner_id, "state": "eq.running", "select": "state", "limit": "1"
    })
    if len(controls) != 1 or controls[0].get("state") != "running":
        raise OutboundBlocked("Outbound blocked: automation is paused or emergency-stopped.")
    switches = read_rows("channel_controls", key, {
        "owner_id": "eq." + owner_id, "channel": "eq." + channel,
        "enabled": "eq.true", "select": "enabled", "limit": "1"
    })
    if len(switches) != 1 or switches[0].get("enabled") is not True:
        raise OutboundBlocked("Outbound blocked: channel is not explicitly enabled.")
    if recipient:
        normalized = re.sub(r"[^a-z0-9@+.]", "", str(recipient).strip().lower())
        if not normalized:
            raise OutboundBlocked("Outbound blocked: recipient cannot be normalized.")
        suppressions = read_rows("contact_suppressions", key, {
            "owner_id": "eq." + owner_id,
            "contact_normalized": "eq." + normalized,
            "channel": "in.(email,all)",
            "select": "id",
            "limit": "1",
        })
        if suppressions:
            raise OutboundBlocked("Outbound blocked: recipient is in the contact suppression list.")
    return True
