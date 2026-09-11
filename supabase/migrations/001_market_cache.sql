-- Fruit Fly Capital: durable DexScreener discovery cache.
-- Run this in the Supabase SQL editor before enabling discovery persistence.
-- The backend uses the service-role key and the browser never talks to these
-- tables directly.

create table if not exists public.market_candidates (
  market_id text primary key,
  token_id text not null,
  chain_id text not null,
  dex_id text not null,
  pair_address text not null,
  represented_token_address text not null,
  symbol text not null default '',
  name text not null default '',
  quote_symbol text,
  image_url text,
  liquidity_usd double precision not null default 0,
  volume_5m_usd double precision,
  volume_1h_usd double precision,
  volume_24h_usd double precision,
  buys_5m integer,
  sells_5m integer,
  buys_1h integer,
  sells_1h integer,
  price_change_5m double precision,
  price_change_1h double precision,
  price_change_24h double precision,
  pair_created_at_ms bigint,
  websites jsonb not null default '[]'::jsonb,
  socials jsonb not null default '[]'::jsonb,
  provenance jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create index if not exists market_candidates_token_idx
  on public.market_candidates (token_id);
create index if not exists market_candidates_seen_idx
  on public.market_candidates (last_seen_at desc);
create index if not exists market_candidates_liquidity_idx
  on public.market_candidates (liquidity_usd desc);

create table if not exists public.market_rounds (
  round_id text primary key,
  round_number bigint not null,
  started_at_ms bigint not null,
  expires_at_ms bigint not null,
  core_markets jsonb not null default '[]'::jsonb,
  recent_markets jsonb not null default '[]'::jsonb,
  markets jsonb not null default '[]'::jsonb,
  deep_markets jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists market_rounds_active_idx
  on public.market_rounds (expires_at_ms, started_at_ms desc);

-- RLS prevents an accidentally exposed anon key from reading the cache.
-- The server's service-role key bypasses RLS. Keep these tables server-only.
alter table public.market_candidates enable row level security;
alter table public.market_rounds enable row level security;
