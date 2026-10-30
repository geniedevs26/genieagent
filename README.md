# GenieAgent

Owner-only automated client acquisition system: scheduled public research, strict lead qualification, private CRM sync, audit trail, and financial approval gate.

## Live app and source
- Live dashboard: https://genieagent.pages.dev/
- Repository: https://github.com/geniedevs26/genieagent
- Daily workflow: https://github.com/geniedevs26/genieagent/actions/workflows/daily-lead-research.yml

## Automated workflow
1. GitHub Actions runs every four hours (cron `0 */4 * * *`), plus on configured code changes or manual dispatch.
2. Public search results are discovery hints only. A research candidate requires requirement wording on the source page; a public email is optional because a verified business contact form may be the contact route. Search snippets alone are discarded.
3. Unverified research candidates sync to the owner's private Supabase CRM with status `research`. They are not confirmed buyers and must not be contacted until the client identity, current requirement, contact route and applicable outreach rules are verified.
4. Financial approval is required before any agreement, quote that creates a commitment, purchase, paid tool, or spending. Discovery does not create an approval or imply a client order.
5. Inserts, updates and deletes for leads, outreach actions, finance entries, workflow runs and financial approvals are captured in `automation_events`. The dashboard displays the latest audit events and financial approval queue.
6. Duplicate website records are skipped. Existing CRM records are not overwritten by research sync.

## One-time setup
In GitHub **Settings → Secrets and variables → Actions → New repository secret**, configure:
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase project server-side service-role/secret key. Keep it secret; never paste it in chat or commit it.
- `GENIE_OWNER_EMAIL`: exact email of the owner account in Supabase Authentication.

Without those two secrets, the workflow safely skips private CRM sync. No recurring manual lead entry is intended; lead research and qualifying records are automated after this one-time setup. For automatic initial email outreach (maximum 5/day, only after requirement and contact verification), also add `SMTP_HOST`, `SMTP_PORT` (normally `587`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `GENIE_SENDER_EMAIL`, and `AUTO_OUTREACH_ENABLED` with value `true`. Use an SMTP account you control; for Gmail, use an App Password if your account supports it, never your normal password. The sender must be authorized to send from `GENIE_SENDER_EMAIL`. If any sender setting is missing, outreach safely skips. Every send attempt is logged before execution; only initial inquiries are sent—no automatic follow-ups, quotes, or payment requests.

## Financial permission boundary
Financial approvals are deliberately **not automatic**. Confirm the real project scope, client budget/payment, revenue, all costs, net profit, pricing evidence and payment terms before approving. Discovery alone cannot approve spending or a quote. Approval is recorded in the private database and audit history.

## Outbound actions
Automatic initial email outreach is wired into the workflow but remains inactive until SMTP secrets are configured. It sends at most five initial emails per day to leads marked qualified with both `clientNeedConfirmed=Yes` and `contactVerified=Yes`; previous attempts are not repeated. Inbox/reply monitoring, automatic follow-ups, and calling are NOT connected in this repository and must not be described as active. Quotes involving commitments, agreements, paid tools and spending remain blocked until owner approval.

## Security and records
- Supabase RLS restricts database rows to the authenticated owner.
- Public repository files must not contain lead lists, credentials, API keys or private customer information.
- Export CSV is a backup convenience, not the source of truth; Supabase plus `automation_events` is the persistent record.
- Research is limited by public-page availability and matching evidence; zero results is preferable to inventing confirmed buyer intent.

## Run locally
```bash
python scripts/lead_research.py
```

Cloudflare Pages should use framework preset **None**, no build command, and `/` as the output directory. A new commit deploys when the Pages Git integration is active.
