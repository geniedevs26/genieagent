create table if not exists public.research_pages (
  owner_id uuid not null,
  url text not null,
  domain text,
  source_name text,
  outcome text not null default 'checked',
  evidence_excerpt text,
  checked_at timestamptz not null default now(),
  next_check_at timestamptz not null default (now() + interval '30 days'),
  created_at timestamptz not null default now(),
  primary key (owner_id, url)
);
alter table public.research_pages enable row level security;
drop policy if exists "Users manage their own research pages" on public.research_pages;
create policy "Users manage their own research pages"
  on public.research_pages for all to authenticated
  using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);
create index if not exists idx_research_pages_next_check
  on public.research_pages(owner_id, next_check_at);

alter table public.approval_requests
  add column if not exists executed_at timestamptz,
  add column if not exists result_notes text,
  add column if not exists outreach_action_id uuid references public.outreach_actions(id) on delete set null;
alter table public.approval_requests
  drop constraint if exists approval_requests_status_check;
alter table public.approval_requests
  add constraint approval_requests_status_check
  check (status in ('pending','approved','rejected','cancelled','executing','executed','failed','needs_review'));

alter table public.client_orders
  drop constraint if exists client_orders_order_status_check;
alter table public.client_orders
  add constraint client_orders_order_status_check
  check (order_status in (
    'awaiting_financial_approval','financial_proposal_approved','financial_proposal_sent',
    'awaiting_agreement_approval','agreement_approved','agreement_sent',
    'awaiting_project_start_approval','in_progress','awaiting_milestone_approval',
    'awaiting_final_delivery_approval','final_delivery_sent',
    'awaiting_order_close_approval','completed','cancelled'
  ));
alter table public.client_orders
  add column if not exists proposal_sent_at timestamptz,
  add column if not exists agreement_sent_at timestamptz,
  add column if not exists project_started_at timestamptz,
  add column if not exists final_delivered_at timestamptz,
  add column if not exists completed_at timestamptz;

drop trigger if exists audit_research_pages_changes on public.research_pages;
create trigger audit_research_pages_changes
after insert or update or delete on public.research_pages
for each row execute function public.audit_genieagent_change();
