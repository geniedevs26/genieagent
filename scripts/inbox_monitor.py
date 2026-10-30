#!/usr/bin/env python3
"""Read the configured mailbox for replies and delivery bounces.

Optional GitHub Actions secrets:
  IMAP_HOST, IMAP_PORT (993), IMAP_USERNAME, IMAP_PASSWORD, IMAP_FOLDER (INBOX)
The monitor never sends email. A genuine inbound reply is evidence that the original
message reached a responding mailbox; SMTP acceptance alone is never marked delivered.
"""
import email
import imaplib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
BOUNCE_RE = re.compile(r"undeliver|delivery status notification|delivery failure|returned mail|mail delivery failed|address not found|user unknown|recipient rejected|550 5\.", re.I)


def api(path, key, method="GET", payload=None, prefer=None):
    headers = {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(SUPABASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read().decode("utf-8", "replace")
            return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Supabase API error " + str(exc.code) + ": " + exc.read().decode("utf-8", "replace")[:500])


def decoded(value):
    parts = decode_header(value or "")
    return " ".join((p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p) for p, enc in parts)


def body_text(msg):
    chunks = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            chunks.append(raw.decode(part.get_content_charset() or "utf-8", "replace"))
        except Exception:
            continue
    return re.sub(r"<[^>]+>", " ", " ".join(chunks))


def main():
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    owner_email = os.getenv("GENIE_OWNER_EMAIL", "").strip().lower()
    host = os.getenv("IMAP_HOST", "").strip()
    username = os.getenv("IMAP_USERNAME", "").strip()
    password = os.getenv("IMAP_PASSWORD", "").strip()
    port = int(os.getenv("IMAP_PORT") or "993")
    folder = os.getenv("IMAP_FOLDER") or "INBOX"
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not all([key, owner_email, host, username, password]):
        msg = "Inbox monitor skipped safely: configure IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD, SUPABASE_SERVICE_ROLE_KEY and GENIE_OWNER_EMAIL."
        print(msg)
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n## Inbox monitoring\n\n" + msg + "\n")
        return 0

    users = api("/auth/v1/admin/users?page=1&per_page=100", key) or {}
    owner = next((u for u in users.get("users", []) if (u.get("email") or "").lower() == owner_email), None)
    if not owner:
        raise RuntimeError("Owner email not found in Supabase Auth.")
    owner_id = owner["id"]
    query = urllib.parse.urlencode({
        "owner_id": "eq." + owner_id,
        "action_type": "in.(email,follow_up,inbound_reply)",
        "select": "id,lead_id,recipient,approval_status,draft_subject",
        "order": "created_at.desc",
        "limit": "2000",
    })
    actions = api("/rest/v1/outreach_actions?" + query, key) or []
    sent_by_recipient = {}
    processed_ids = set()
    for action in actions:
        if action.get("action_type") == "inbound_reply":
            match = re.search(r"Message-ID:\s*(.+)$", action.get("draft_subject") or "")
            if match:
                processed_ids.add(match.group(1).strip())
        elif action.get("recipient") and action.get("approval_status") in ("pending_verification", "delivered", "delivery_verified"):
            sent_by_recipient[action["recipient"].lower()] = action

    leads = api("/rest/v1/leads?" + urllib.parse.urlencode({
        "owner_id": "eq." + owner_id, "select": "id,payload", "limit": "2000"
    }), key) or []
    leads_by_id = {row["id"]: row for row in leads}
    mail = imaplib.IMAP4_SSL(host, port)
    processed = replies = bounces = ignored = 0
    try:
        mail.login(username, password)
        status, _ = mail.select(folder)
        if status != "OK":
            raise RuntimeError("Could not open IMAP folder " + folder)
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Could not search unread mailbox messages")
        for msg_num in (data[0].split() if data and data[0] else []):
            status, parts = mail.fetch(msg_num, "(RFC822)")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            raw = parts[0][1]
            msg = email.message_from_bytes(raw)
            message_id = (msg.get("Message-ID") or "").strip()
            if message_id and message_id in processed_ids:
                mail.store(msg_num, "+FLAGS", "\\Seen")
                continue
            sender = parseaddr(msg.get("From", ""))[1].lower()
            subject = decoded(msg.get("Subject", ""))
            text = body_text(msg)
            combined = subject + "\n" + text
            is_bounce = bool(BOUNCE_RE.search(combined) or sender.startswith(("mailer-daemon@", "postmaster@")))
            recipient = ""
            if is_bounce:
                candidates = [e.lower() for e in EMAIL_RE.findall(combined) if e.lower() != sender]
                recipient = next((e for e in candidates if e in sent_by_recipient), "")
                if not recipient:
                    ignored += 1
                    continue
                original = sent_by_recipient[recipient]
                now = datetime.now(timezone.utc).isoformat()
                api("/rest/v1/outreach_actions?id=eq." + original["id"], key, "PATCH", {
                    "approval_status": "bounced", "result_notes": "Mailbox monitor detected a delivery failure/bounce. Recipient delivery is not verified; do not retry automatically."
                }, "return=minimal")
                lead = leads_by_id.get(original.get("lead_id"))
                if lead:
                    payload = lead.get("payload") if isinstance(lead.get("payload"), dict) else {}
                    payload["emailDeliveryStatus"] = "bounced"
                    payload["contactVerified"] = "No"
                    payload["activity"] = (payload.get("activity") if isinstance(payload.get("activity"), list) else []) + [{
                        "date": now[:10], "text": "Email bounce detected for " + recipient + "; email contact verification revoked."
                    }]
                    api("/rest/v1/leads?id=eq." + original["lead_id"], key, "PATCH", {
                        "payload": payload, "updated_at": now
                    }, "return=minimal")
                api("/rest/v1/automation_events", key, "POST", {
                    "owner_id": owner_id, "event_type": "email_bounced", "entity_table": "outreach_actions",
                    "entity_id": original["id"], "event_status": "bounced",
                    "summary": "Mailbox monitor detected a bounce; recipient excluded from verified delivery totals.",
                    "details": {"lead_id": original.get("lead_id"), "recipient": recipient, "subject": subject[:180]}
                }, "return=minimal")
                bounces += 1
            else:
                original = sent_by_recipient.get(sender)
                if not original:
                    ignored += 1
                    continue
                now = datetime.now(timezone.utc).isoformat()
                api("/rest/v1/outreach_actions?id=eq." + original["id"], key, "PATCH", {
                    "approval_status": "delivery_verified", "result_notes": "A genuine reply from the recipient was received. This confirms the original email reached a responding mailbox; it is counted as delivery-verified."
                }, "return=minimal")
                lead = leads_by_id.get(original.get("lead_id"))
                if lead:
                    payload = lead.get("payload") if isinstance(lead.get("payload"), dict) else {}
                    payload["status"] = "Replied"
                    payload["emailDeliveryStatus"] = "reply_received"
                    payload["lastClientReplyAt"] = now
                    payload["activity"] = (payload.get("activity") if isinstance(payload.get("activity"), list) else []) + [{
                        "date": now[:10], "text": "Inbound email reply received from " + sender + ". Review the original message in your mailbox."
                    }]
                    api("/rest/v1/leads?id=eq." + original["lead_id"], key, "PATCH", {
                        "payload": payload, "lead_status": "replied", "updated_at": now
                    }, "return=minimal")
                api("/rest/v1/outreach_actions", key, "POST", {
                    "owner_id": owner_id, "lead_id": original.get("lead_id"), "action_type": "inbound_reply",
                    "recipient": sender, "approval_status": "replied",
                    "draft_subject": "Message-ID: " + (message_id or ("no-id-" + str(msg_num))),
                    "result_notes": "Inbound reply received. The original message reached a responding mailbox; read the full reply in the mailbox. No response was sent."
                }, "return=minimal")
                api("/rest/v1/automation_events", key, "POST", {
                    "owner_id": owner_id, "event_type": "client_email_reply", "entity_table": "outreach_actions",
                    "entity_id": original["id"], "event_status": "replied",
                    "summary": "Inbound client reply detected; no automatic response sent.",
                    "details": {"lead_id": original.get("lead_id"), "sender": sender, "subject": subject[:180]}
                }, "return=minimal")
                replies += 1
            mail.store(msg_num, "+FLAGS", "\\Seen")
            processed += 1
    finally:
        try:
            mail.close()
        except Exception:
            pass
        mail.logout()

    msg = f"Inbox monitor completed: {replies} replies detected, {bounces} bounces detected, {ignored} unrelated/unmatched messages left unread."
    print(msg)
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n## Inbox monitoring\n\n" + msg + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("Inbox monitoring failed safely: " + str(exc), file=sys.stderr)
        sys.exit(1)
