# GenieAgent

Owner-only client acquisition dashboard for research, lead tracking, outreach drafts, and a simple income/expense ledger.

## Live app
- Cloudflare Pages: https://genieagent.pages.dev/
- Repository: https://github.com/geniedevs26/genieagent

## Dashboard
- Sign in using the owner account created in Supabase Authentication. Public account creation is disabled.
- Lead records sync to the authenticated Supabase database when cloud access is available; CSV import/export is available for backup.
- Use the quick navigation for Add lead, Lead pipeline, Outreach drafts, Income & costs, and Automation.
- Outreach tools prepare drafts and open local email/calling apps. They do not automatically send messages or place calls.
- Opt-out / not-interested states block outreach drafts. Verify actual requirements and contact details before treating any research result as a lead.

## Daily research automation
GitHub Actions runs the public-web candidate research workflow daily at **01:00 UTC / 06:30 India time**. It can also be started manually from **Actions → Daily public lead research → Run workflow**.

The workflow searches public web results and writes candidate rows only to the temporary runner. It publishes a safe run summary/count only; it does **not** publish contact details, save candidate rows into the CRM, or qualify prospects automatically. The dashboard's **Daily Automation** button opens the workflow page.

### Current automation boundary
The daily public-web research schedule is active. The workflow now supports automatic owner-scoped syncing into the private Supabase CRM when these two repository secrets are configured: `SUPABASE_SERVICE_ROLE_KEY` and `GENIE_OWNER_EMAIL`. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**. Add `SUPABASE_SERVICE_ROLE_KEY` using the Supabase project’s service-role/secret key (Project Settings → API Keys) and `GENIE_OWNER_EMAIL` using the exact email of the owner’s Supabase Auth account. Never paste the service key into chat or commit it to the repository. If either secret is missing, the workflow safely skips syncing and reports that status; the research run still completes. Once configured, the workflow inserts only new unverified candidates into the owner’s CRM, skips existing website matches, and does not overwrite existing leads or mark candidates qualified. Do not upload lead lists or credentials into this public repository.

## Security and costs
- Never commit API keys, passwords, client contact lists, or private lead data.
- `_headers` adds browser/security headers and no-index hints; those headers are not a login system.
- Keep Supabase RLS enabled and verify owner-only policies before changing database access.
- Use free tiers where suitable. Disclose any paid API, hosting, domain, or recurring service cost before a client commits.
- Every external email, call, proposal, and follow-up needs a separate review and explicit approval. Automated outbound actions are not enabled.
- The agreement output is a discussion draft, not legal advice.

## Run research locally
```bash
python scripts/lead_research.py
```

## Deploy
Cloudflare Pages should be connected to this GitHub repository with framework preset **None**, no build command, and repository root (`/`) as the build output directory. A new commit triggers deployment when the Pages Git integration is active.
