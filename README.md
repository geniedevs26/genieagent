# GenieDevs Client Acquisition Agent

A zero-cost, static browser-based lead CRM and outreach drafting workspace for GenieDevs.

## Deploy to Cloudflare Pages
1. Open Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git.
2. Select `geniedevs26/genieagent`.
3. Framework preset: **None**.
4. Build command: leave blank.
5. Build output directory: `/` (repository root).
6. Deploy. The app is served from `index.html`.

## Features
- Lead records with country, public business contact, website, source URL, service opportunity, and a required business-specific observation.
- Search/filter pipeline and activity timeline.
- Drafts for initial email, follow-up, call opening, proposal outline, and agreement discussion draft.
- CSV import/export backups; duplicate check on non-empty email addresses.
- Opt-out and not-interested statuses block draft generation; opt-out is locked against accidental changes in the UI.
- Browser localStorage only; data stays in this browser profile unless exported.

## Current boundaries
This is a static front-end MVP. It does **not** automatically discover or verify 20 leads per day, scrape websites, send emails, place PSTN calls, schedule background follow-ups, or synchronize between devices. No API keys or credentials are included. Automated research, sending, and calling require separate integrations, permission checks, and legal compliance.

## Privacy and security
Do not enter passwords, payment details, or sensitive personal information. Export CSV backups regularly. Clearing browser storage or using another browser/device may remove or hide records. Review drafts for accuracy before sending. The agreement output is a discussion draft, not legal advice.
