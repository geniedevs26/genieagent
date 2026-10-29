# GenieAgent

Static client-acquisition desk plus a daily public-web lead research workflow.

## Daily research and data privacy
GitHub Actions runs at 01:00 UTC (06:30 India time) and can also be started manually from **Actions → Daily public lead research → Run workflow**. It searches public Bing RSS results and checks public business/contact pages. Because this repository is currently public, the workflow now reports only a count and does **not** commit or upload lead details. Persistent candidate storage must be connected to authenticated private storage before that part of automation is re-enabled.

## Important review step
These are **candidates**, not verified prospects. Search snippets can be misleading and emails may be absent or stale. Verify the business, the actual opportunity, and the published contact method before contacting anyone. The workflow does not send emails, place calls, bypass access controls, or make claims on your behalf.

## Run locally
```bash
python scripts/lead_research.py
```

## Security status and outbound actions
- This repository is public, so source code and tracked files are visible to everyone. Do not put API keys, passwords, private client data, or lead contact lists in this repository.
- `_headers` adds browser/security headers and no-index hints, but those headers do not provide login protection.
- The static app is not yet protected by a login gate and currently stores CRM records in browser localStorage only.
- Email sending and phone calling are not connected to the live app yet. The current buttons prepare drafts and open local apps; they do not automatically send messages or place provider calls.
- Before enabling outbound execution, protect the production hostname with Cloudflare Access (allow only the owner's email), connect a private authenticated data store, and configure a verified email provider and a telephony provider as Cloudflare secrets. Every send/call/proposal/follow-up must require a per-action review and explicit approval; proposals additionally require the financial gate.
- Automated calling requires a telephony account and can incur charges. Do not enable it until the owner phone, caller ID, consent/compliance settings, and per-call approval are verified.

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
The scheduled workflow searches public web results and writes candidate rows to `data/research_candidates.csv` only inside its temporary GitHub Actions runner. The workflow reports a count in the Actions summary and does not commit or upload candidate details. There is currently no persistent private lead database and no qualified-lead feed; the app's lead-loader button reports this state. Use manual verification and the app's Add a lead / Import CSV functions until private storage is configured. The workflow does not send emails or place calls.

## Privacy and security
Do not enter passwords, payment details, or sensitive personal information. Export CSV backups regularly. Review candidates and drafts before outreach. The agreement output is a discussion draft, not legal advice.
