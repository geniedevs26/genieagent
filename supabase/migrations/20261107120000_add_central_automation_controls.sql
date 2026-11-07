-- Central owner-controlled automation and channel kill switches.
-- New installations start PAUSED with every outbound channel disabled.
create table if not exists public.automation_controls (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  state text not null default 'paused'
    check (state in ('paused','running','emergency_stopped')),
  reason text,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id)
);

create table if not exists public.channel_controls (
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel text not null
    check (channel in ('email','follow_up','ai_reply','client_stage_email')),
  enabled boolean not null default false,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id),
  primary key (owner_id, channel)
);

alter table public.automation_controls enable row level security;
alter table public.channel_controls enable row level security;

drop policy if exists automation_controls_owner_all on public.automation_controls;
create policy automation_controls_owner_all
  on public.automation_controls for all
  to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

drop policy if exists channel_controls_owner_all on public.channel_controls;
create policy channel_controls_owner_all
  on public.channel_controls for all
  to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

grant select, insert, update, delete on public.automation_controls to authenticated;
grant select, insert, update, delete on public.channel_controls to authenticated;
grant all on public.automation_controls to service_role;
grant all on public.channel_controls to service_role;

create index if not exists channel_controls_owner_enabled_idx
  on public.channel_controls(owner_id, enabled);

comment on table public.automation_controls is
  'Owner-only global automation state. Missing row means paused.';
comment on table public.channel_controls is
  'Owner-only per-channel outbound switches. Missing row means disabled.';
