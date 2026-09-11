-- Persist every biological BUY/SELL proposal before execution eligibility is
-- decided. Observed rows are audit records; only pending rows are claimable.

alter table public.execution_intents
  drop constraint if exists execution_intents_status_check;

alter table public.execution_intents
  add constraint execution_intents_status_check
  check (status in ('observed', 'pending', 'claimed', 'prepared', 'broadcast', 'confirmed', 'failed'));

alter table public.execution_intents
  add column if not exists behavior_intent_id text,
  add column if not exists execution_eligible boolean not null default true,
  add column if not exists proposal_reason text;

create unique index if not exists execution_intents_behavior_intent_idx
  on public.execution_intents (behavior_intent_id)
  where behavior_intent_id is not null;

create index if not exists execution_intents_observed_idx
  on public.execution_intents (created_at desc)
  where status = 'observed';
