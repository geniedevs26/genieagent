# GenieAgent

Owner-only client acquisition automation: persistent public research, automatic qualification of direct-business requirements, initial outreach, up to three bounded reply-aware follow-ups, client-response monitoring, and stage-by-stage owner approval for every post-interest project action.

## Live app and source
- Live dashboard: https://genieagent.pages.dev/
- Repository: https://github.com/geniedevs26/genieagent
- Scheduled workflow: https://github.com/geniedevs26/genieagent/actions/workflows/daily-lead-research.yml

## Automated prospecting workflow
1. GitHub Actions runs hourly (cron 17 * * * *).
2. Public search snippets are discovery hints only. The source page must contain first-person business intent, a nearby paid/contract signal, and no job-board/unpaid indicators.
3. The page must be on the business's own website and expose a public business email. The research worker checks the contact page, then records the page URL, evidence excerpt, provider and next recheck time in the private research_pages table.
4. Research cursor state is persistent. Recently checked pages are skipped; fetch failures are retried sooner; non-matching pages are rechecked later. Search therefore progresses beyond the same first 40 results on every run.
5. Only automatically verified direct-business requirements with a public same-site email enter leads as qualified. Unverified pages and contact-form-only pages are not treated as qualified email leads.
6. The system sends a relevant initial inquiry automatically. Up to three follow-ups may be sent on days 5, 12 and 21 after the initial email, only when inbox monitoring is configured and no reply, bounce or opt-out has been detected. A reply, bounce or opt-out stops further follow-up; after day 21 the lead is paused. SMTP acceptance is never described as confirmed delivery.
7. A client reply requesting a quote/proposal creates a private client-order opportunity and a pending financial-proposal approval. The system does not send a proposal at this point.

## Owner approval after client interest
Every post-interest stage has a separate approval request in the dashboard's Orders & approvals view:

1. **Financial proposal:** complete the financial review (scope, budget, amount, all costs, net profit, payment terms and current pricing evidence), edit the exact proposal, then approve. The hourly executor sends only after both financial review and stage approval pass.
2. **Agreement:** after the client accepts the proposal, an agreement draft is queued. Edit and approve before it is sent.
3. **Project start:** after the client accepts the agreement, a separate start approval is queued. The project does not advance until approved.
4. **Milestone delivery:** upload the deliverable to a location you control, enter the URL and message, then approve before the email is sent.
5. **Final delivery:** same separate upload, review and approval gate.
6. **Order closure:** after the client explicitly accepts final delivery, a closure approval is queued. The order is marked completed only after owner approval.

An approval click queues execution for the next hourly workflow run; it does not itself send the message. If a required financial field or document placeholder remains incomplete, execution is blocked. Ambiguous SMTP failures are held for review and are not retried automatically.

## Required GitHub Actions secrets
For private Supabase sync and research cursor:
- SUPABASE_SERVICE_ROLE_KEY
- GENIE_OWNER_EMAIL

For initial outreach, follow-up and approved-stage emails:
- SMTP_HOST
- SMTP_PORT (normally 587)
- SMTP_USERNAME
- SMTP_PASSWORD (provider app password/credential)
- GENIE_SENDER_EMAIL
- Optional SUPPRESSED_EMAILS (comma-separated addresses that must never be contacted)\n\nFor bounded AI email replies (Cloudflare Workers AI free allocation):\n- CLOUDFLARE_AI_ACCOUNT_ID\n- CLOUDFLARE_AI_API_TOKEN (Workers AI API token with Workers AI Read permission; keep only in GitHub Actions Secrets)\n\nWorkers AI currently includes 10,000 Neurons/day on the Free Workers plan. GenieAgent caps itself at three low-risk AI replies per UTC day. Keep the Cloudflare account on the Free plan and do not add paid credits or upgrade. If the daily free allocation is exhausted, AI replies fail closed and are held.

For inbox reply/bounce, AI email replies and client-stage monitoring:
- IMAP_HOST
- IMAP_PORT (normally 993)
- IMAP_USERNAME
- IMAP_PASSWORD
- Optional IMAP_FOLDER (normally INBOX)

These credentials belong only in GitHub Actions Secrets. Do not paste them into chat or commit them. AUTO_OUTREACH_ENABLED is set by the workflow after the qualification and suppression gates; it is not a repository secret.

## Calling
Automatic AI phone calling is not connected. A compliant PSTN calling route is required to reach ordinary mobile/landline numbers; browser/WebRTC software alone does not provide free PSTN minutes. No genuinely zero-cost provider with verified ongoing India outbound calling has been found, and no paid provider is configured. No call is claimed as placed.

## Security and records
- Supabase RLS restricts CRM, orders, approval requests and research cursor records to the owner.
- Candidate and client details are not committed to this public repository or uploaded as workflow artifacts.
- automation_events records research, outreach, replies, bounces, approvals and stage transitions.
- A public email address and a published requirement are evidence of a contact route and stated need, not a guarantee of email delivery, available budget or an accepted order.
- Opt-outs and detected bounces suppress future automated outreach.
- Research prefers zero results to invented or weak leads.

## Run locally
~~~bash
python scripts/lead_research.py
python scripts/sync_candidates_supabase.py
python scripts/inbox_monitor.py
python scripts/auto_outreach.py
python scripts/execute_approved_actions.py
~~~

Cloudflare Pages uses framework preset None, no build command, and / as the output directory. A new commit deploys when the Pages Git integration is active.


## Optional AI email replies
See [AI reply setup](docs/AI_REPLY_SETUP.md) for the optional, guarded Cloudflare Workers AI responder, daily cap, and one-time GitHub Secrets configuration.
