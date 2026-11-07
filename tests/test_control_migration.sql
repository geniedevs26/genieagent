-- PostgreSQL integration test for 20261107120000_add_central_automation_controls.sql
insert into auth.users(id) values
 ('11111111-1111-4111-8111-111111111111'),
 ('22222222-2222-4222-8222-222222222222')
on conflict do nothing;

insert into public.automation_controls(owner_id,state)
values ('11111111-1111-4111-8111-111111111111','paused');

insert into public.channel_controls(owner_id,channel,enabled)
values ('11111111-1111-4111-8111-111111111111','email',false);

-- Authenticated owner A can read and change only their own settings.
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-4111-8111-111111111111';
do $$
begin
  if (select count(*) from public.automation_controls) <> 1 then
    raise exception 'owner A cannot read their own control row';
  end if;
  if (select state from public.automation_controls) <> 'paused' then
    raise exception 'new automation state must be paused';
  end if;
  if (select enabled from public.channel_controls where channel='email') is distinct from false then
    raise exception 'new outbound channel must be disabled';
  end if;
end $$;
update public.automation_controls set state='running'
where owner_id='11111111-1111-4111-8111-111111111111';
update public.channel_controls set enabled=true
where owner_id='11111111-1111-4111-8111-111111111111' and channel='email';
do $$
begin
  if (select state from public.automation_controls) <> 'running' then
    raise exception 'owner A could not update their own automation state';
  end if;
  if (select enabled from public.channel_controls where channel='email') is distinct from true then
    raise exception 'owner A could not enable their own channel';
  end if;
end $$;
reset role;

-- Owner B cannot see or modify owner A's controls.
set role authenticated;
set request.jwt.claim.sub = '22222222-2222-4222-8222-222222222222';
do $$
begin
  if (select count(*) from public.automation_controls) <> 0 then
    raise exception 'RLS leak: owner B can see owner A controls';
  end if;
end $$;
update public.automation_controls set state='emergency_stopped'
where owner_id='11111111-1111-4111-8111-111111111111';
reset role;

-- Service-role worker can read the owner controls needed for enforcement.
set role service_role;
do $$
begin
  if (select state from public.automation_controls
      where owner_id='11111111-1111-4111-8111-111111111111') <> 'running' then
    raise exception 'service role cannot read controls';
  end if;
end $$;
reset role;
