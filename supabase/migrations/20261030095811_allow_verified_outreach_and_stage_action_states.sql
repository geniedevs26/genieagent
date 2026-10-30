alter table public.outreach_actions
  drop constraint if exists outreach_actions_action_type_check;
alter table public.outreach_actions
  add constraint outreach_actions_action_type_check
  check (action_type in (
    'email','call','proposal','follow_up','other','inbound_reply',
    'agreement','milestone_delivery','final_delivery'
  ));
alter table public.outreach_actions
  drop constraint if exists outreach_actions_approval_status_check;
alter table public.outreach_actions
  add constraint outreach_actions_approval_status_check
  check (approval_status in (
    'pending','approved','rejected','sent','failed','cancelled',
    'pending_verification','delivery_verified','bounced','replied',
    'executing','executed','needs_review'
  ));
