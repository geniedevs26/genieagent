alter table public.leads
  add column if not exists contact_phone text,
  add column if not exists phone_source_url text,
  add column if not exists phone_verified_at timestamptz,
  add column if not exists outreach_attempts integer not null default 0,
  add column if not exists last_outreach_at timestamptz,
  add column if not exists client_confirmed_at timestamptz,
  add column if not exists deal_stage text not null default 'prospecting';

create table if not exists public.client_orders (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid(),
  lead_id uuid not null references public.leads(id) on delete restrict,
  client_name text not null,
  scope_summary text not null,
  agreed_currency text not null default 'USD',
  agreed_amount numeric(12,2),
  payment_terms text,
  target_date date,
  order_status text not null default 'awaiting_financial_approval'
    check (order_status in (
      'awaiting_financial_approval','financial_proposal_approved','financial_proposal_sent',
      'awaiting_agreement_approval','agreement_approved','agreement_sent',
      'awaiting_project_start_approval','in_progress','awaiting_milestone_approval',
      'awaiting_final_delivery_approval','completed','cancelled'
    )),
  client_accepted_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, lead_id)
);

create table if not exists public.approval_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid(),
  order_id uuid not null references public.client_orders(id) on delete cascade,
  lead_id uuid not null references public.leads(id) on delete restrict,
  stage text not null check (stage in (
    'financial_proposal_send','agreement_send','project_start',
    'milestone_delivery','final_delivery','order_close'
  )),
  title text not null,
  document_subject text,
  document_body text,
  document_url text,
  status text not null default 'pending' check (status in ('pending','approved','rejected','cancelled')),
  requested_at timestamptz not null default now(),
  decided_at timestamptz,
  decision_notes text,
  created_at timestamptz not null default now()
);

create index if not exists idx_client_orders_owner_status
  on public.client_orders(owner_id, order_status, updated_at desc);
create index if not exists idx_approval_requests_owner_status
  on public.approval_requests(owner_id, status, requested_at desc);
create index if not exists idx_approval_requests_order_stage
  on public.approval_requests(order_id, stage, requested_at desc);
create unique index if not exists uq_approval_pending_stage
  on public.approval_requests(order_id, stage)
  where status = 'pending';

alter table public.client_orders enable row level security;
alter table public.approval_requests enable row level security;

drop policy if exists "Users manage their own client orders" on public.client_orders;
create policy "Users manage their own client orders"
  on public.client_orders for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

drop policy if exists "Users manage their own approval requests" on public.approval_requests;
create policy "Users manage their own approval requests"
  on public.approval_requests for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_client_orders_updated_at on public.client_orders;
create trigger set_client_orders_updated_at
before update on public.client_orders
for each row execute function public.set_updated_at();

drop trigger if exists audit_client_orders_changes on public.client_orders;
create trigger audit_client_orders_changes
after insert or update or delete on public.client_orders
for each row execute function public.audit_genieagent_change();

drop trigger if exists audit_approval_requests_changes on public.approval_requests;
create trigger audit_approval_requests_changes
after insert or update or delete on public.approval_requests
for each row execute function public.audit_genieagent_change();
