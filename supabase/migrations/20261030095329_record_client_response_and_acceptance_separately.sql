alter table public.client_orders
  alter column client_accepted_at drop not null,
  alter column client_accepted_at drop default;
alter table public.client_orders
  add column if not exists client_response_at timestamptz not null default now(),
  add column if not exists proposal_requested_at timestamptz,
  add column if not exists client_acceptance_evidence text;
