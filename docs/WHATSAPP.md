# WhatsApp providers

Two adapters are implemented behind one interface in
`genieagent/outreach/whatsapp.py`. Selection is configuration only:

```
WHATSAPP_PROVIDER=none        # default: no WhatsApp drafts or sends
WHATSAPP_PROVIDER=meta_cloud  # Meta WhatsApp Cloud API
WHATSAPP_PROVIDER=green_api   # Green API (unofficial WhatsApp client)
```

WhatsApp sending is also gated by `WHATSAPP_SEND_ENABLED=false` (default) and by
the same per-message owner approval as email.

## Consent and privacy rules (enforced)

* A draft is only prepared when the lead has `phone_type=business`, a business
  phone number and a non-empty `consent_basis` (for example: "Owner recorded an
  inbound WhatsApp enquiry on 2026-10-30" or "Business publishes this number for
  enquiries and the owner confirmed permission").
* Personal mobile numbers are never used. The dashboard and logs show masked
  numbers only (`*********67`).
* Opt-outs set `do_not_contact=true` and block every later draft.
* Do not use scraped personal numbers, and do not message people who have not
  consented where local law requires it (for example the EU/UK, India DND rules).

## Meta WhatsApp Cloud API

Configuration:

```
WHATSAPP_PROVIDER=meta_cloud
WHATSAPP_PHONE_NUMBER_ID=...        # Meta app → WhatsApp → API setup
WHATSAPP_ACCESS_TOKEN=...           # temporary 24h token for tests, system user token for production
WHATSAPP_GRAPH_VERSION=v25.0
WHATSAPP_TEMPLATE_NAME=...          # required for first contact
WHATSAPP_TEMPLATE_LANG=en_US
```

Endpoint used: `POST https://graph.facebook.com/{version}/{phone_number_id}/messages`
with a bearer token.

**Template requirement:** Meta only allows free-form text inside a 24-hour
customer-service window. A first contact outside that window must be an approved
message template. The adapter therefore refuses free-form first contact
(`status=blocked`) and, when a template is configured, sends the approved
template with two body parameters: contact/company name and service fit.
Create and get the template approved in Meta Business Manager first.

Test without messaging anyone:

```bash
python - <<'PY'
from genieagent.config import Config
from genieagent.outreach.whatsapp import build_provider
c = Config.from_env()
p = build_provider(c)
print(c.whatsapp_provider, c.whatsapp_ready, p.can_start_conversation if p else None)
PY
```

## Green API

Configuration:

```
WHATSAPP_PROVIDER=green_api
GREEN_API_ID_INSTANCE=...
GREEN_API_TOKEN=...
```

Endpoint used: `POST https://api.green-api.com/waInstance{id}/sendMessage/{token}`
with `{"chatId": "<digits>@c.us", "message": "<text>"}`.

Green API links a normal WhatsApp account through an unofficial client. It can
start conversations with text, but it carries account-ban risk and is not
endorsed by Meta. Use it only if you accept that risk and the consent rules above.
Keep `WHATSAPP_SEND_ENABLED=false` until a test message to your own number works.

## What is verified

* Payload construction, endpoint/URL shape, bearer header placement, phone
  normalisation, template blocking and error mapping are covered by offline
  tests with a fake transport.
* No live WhatsApp message has been sent from this environment because no phone
  number, Meta app or Green API instance is configured.

## Inbound messages

This repository has no always-on webhook server (Termux/GitHub Actions are not
public endpoints). Record replies and opt-outs explicitly:

```bash
python scripts/pipeline_track.py --mark-reply <lead_id> --note "Asked for a quote"
python scripts/pipeline_track.py --mark-optout <lead_id>
```

If you later run a webhook receiver, verify Meta's `X-Hub-Signature-256` and treat
payloads as untrusted.
