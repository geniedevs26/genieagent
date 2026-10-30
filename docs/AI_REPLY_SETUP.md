# AI email reply setup

GenieAgent can answer a narrow set of simple client questions by email. It uses Cloudflare Workers AI with the currently documented free allocation, and is limited to three AI reply attempts per UTC day.

## One-time setup

1. In the Cloudflare dashboard, open **Workers AI** and choose **Use REST API**.
2. Create a Workers AI API token with **Workers AI Read** permission and copy the Account ID.
3. In GitHub, open **geniedevs26/genieagent → Settings → Secrets and variables → Actions**.
4. Add these repository secrets:
   - `CLOUDFLARE_AI_ACCOUNT_ID`
   - `CLOUDFLARE_AI_API_TOKEN`
5. The existing SMTP secrets are also required: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `GENIE_SENDER_EMAIL`.

Never paste tokens into source code, issues, chat messages, or commit history.

## What the AI may answer

Only simple factual questions about the listed services and portfolio, using the approved skill profile. Replies are short, logged in the private CRM and sent in the existing email thread.

The responder holds pricing, quotes, estimates, budget, payment, contract, terms, timeline, deadline, availability, calls/meetings, legal, security, confidential-data and other commitment questions for owner review. It does not accept a project, negotiate, quote, promise a delivery date or agree to terms. If model output is invalid or the filters cannot establish a safe answer, no reply is sent.

## Zero-cost guardrails

Cloudflare documents a 10,000 Neurons/day free allocation on the Workers Free plan. GenieAgent applies a stricter cap of three AI reply attempts per UTC day. Keep the Cloudflare account on the Free Workers plan; do not upgrade or add prepaid credits. If the free allocation is unavailable or exhausted, AI reply generation fails closed and the client message remains recorded for review.

Official documentation:
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/get-started/rest-api/

This feature is email-only. It does not place phone calls to mobile or landline numbers.
