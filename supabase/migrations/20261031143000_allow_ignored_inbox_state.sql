-- Inbox monitor records machine-generated autoresponders as ignored so they are
-- deduplicated without being treated as a buyer reply or an outreach failure.
alter table public.outreach_actions
  drop constraint if exists outreach_actions_approval_status_check;

alter table public.outreach_actions
  add constraint outreach_actions_approval_status_check
  check (approval_status in (
    'pending','approved','rejected','sent','failed','cancelled',
    'pending_verification','delivery_verified','bounced','replied',
    'executing','executed','needs_review','ignored'
  ));
