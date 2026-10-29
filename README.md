# GenieAgent

Static client-acquisition desk plus a daily public-web lead research workflow.

## Daily research
GitHub Actions runs at 01:00 UTC (06:30 India time) and can also be started manually from **Actions → Daily public lead research → Run workflow**. It searches public Bing RSS results, visits public business pages/contact pages, and writes candidate rows to `data/auto_leads.csv`.

## Important review step
These are **candidates**, not verified prospects. Search snippets can be misleading and emails may be absent or stale. Verify the business, the actual opportunity, and the published contact method before contacting anyone. The workflow does not send emails, place calls, bypass access controls, or make claims on your behalf.

## Run locally
```bash
python scripts/lead_research.py
```

## Deploy to Cloudflare Pages
1. Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git.
2. Select `geniedevs26/genieagent`.
3. Framework preset: **None**.
4. Build command: leave blank.
5. Build output directory: `/` (repository root).
6. Deploy. The app is served from `index.html`.

## Existing app features
- Lead records with country, public business contact, website, source URL, service opportunity, and required business-specific observation.
- Search/filter pipeline and activity timeline.
- Drafts for initial email, follow-up, call opening, proposal outline, and agreement discussion draft.
- CSV import/export backups.
- Opt-out and not-interested statuses block draft generation.
- Browser localStorage only; browser records do not sync between devices.

## Current boundaries
The new workflow performs scheduled public-web candidate research and stores results in `data/auto_leads.csv`. It does not send emails, place phone calls, or automatically merge the CSV into the browser's lead list. Those actions require separate service integrations and credentials. No paid keys or credentials are included.

## Privacy and security
Do not enter passwords, payment details, or sensitive personal information. Export CSV backups regularly. Review candidates and drafts before outreach. The agreement output is a discussion draft, not legal advice.
