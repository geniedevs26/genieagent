alter table public.outreach_actions
  drop constraint if exists outreach_actions_action_type_check;

alter table public.outreach_actions
  add constraint outreach_actions_action_type_check
  check (action_type in (
    'email','call','proposal','follow_up','other','inbound_reply',
    'agreement','agreement_send','financial_proposal_send','milestone_delivery',
    'final_delivery','ai_reply'
  ));
