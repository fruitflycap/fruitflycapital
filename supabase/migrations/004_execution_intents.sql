-- Durable cross-service queue for FruitFly Capital execution intents.
-- Run after the market-cache migrations. Writes are server-only.

create table if not exists public.execution_intents (
  idempotency_key text primary key,
  side text not null check (side in ('buy', 'sell')),
  chain_id bigint not null,
  token_in text not null,
  token_out text not null,
  amount_in numeric not null check (amount_in >= 0),
  fly_ids jsonb not null default '[]'::jsonb,
  biological_event_id text,
  payload jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'claimed', 'prepared', 'broadcast', 'confirmed', 'failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  claimed_by text,
  claimed_at timestamptz,
  lease_until timestamptz,
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists execution_intents_pending_idx
  on public.execution_intents (available_at, created_at)
  where status in ('pending', 'claimed');
create index if not exists execution_intents_status_idx
  on public.execution_intents (status, updated_at desc);
create index if not exists execution_intents_created_idx
  on public.execution_intents (created_at desc);

create or replace function public.set_execution_intent_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists execution_intents_updated_at on public.execution_intents;
create trigger execution_intents_updated_at
before update on public.execution_intents
for each row execute function public.set_execution_intent_updated_at();

create or replace function public.claim_execution_intents(
  p_worker_id text,
  p_limit integer default 1,
  p_lease_seconds integer default 120
)
returns setof public.execution_intents
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidates as (
    select idempotency_key
    from public.execution_intents
    where available_at <= now()
      and (status = 'pending' or (status = 'claimed' and lease_until < now()))
    order by created_at
    for update skip locked
    limit greatest(1, least(p_limit, 100))
  )
  update public.execution_intents e
     set status = 'claimed',
         attempts = e.attempts + 1,
         claimed_by = p_worker_id,
         claimed_at = now(),
         lease_until = now() + make_interval(secs => greatest(30, least(p_lease_seconds, 3600))),
         updated_at = now()
    from candidates c
   where e.idempotency_key = c.idempotency_key
  returning e.*;
end;
$$;

alter table public.execution_intents enable row level security;
revoke all on table public.execution_intents from anon, authenticated;
revoke all on function public.claim_execution_intents(text, integer, integer) from public;
grant execute on function public.claim_execution_intents(text, integer, integer) to service_role;
