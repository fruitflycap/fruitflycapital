-- Add the provider facts needed to compare valuation with executable LP depth.
-- Apply after 001_market_cache.sql. Nullable means "not supplied by the
-- provider", never "zero".

alter table public.market_candidates
  add column if not exists price_usd double precision,
  add column if not exists price_native double precision,
  add column if not exists fdv_usd double precision,
  add column if not exists market_cap_usd double precision,
  add column if not exists liquidity_base double precision,
  add column if not exists liquidity_quote double precision,
  add column if not exists txns_24h integer,
  add column if not exists boosts_active integer,
  add column if not exists pair_age_hours double precision,
  add column if not exists market_cap_to_liquidity double precision,
  add column if not exists fdv_to_liquidity double precision,
  add column if not exists volume_24h_to_market_cap double precision,
  add column if not exists volume_24h_to_liquidity double precision;

create index if not exists market_candidates_market_cap_liquidity_idx
  on public.market_candidates (market_cap_to_liquidity);

create index if not exists market_candidates_volume_liquidity_idx
  on public.market_candidates (volume_24h_to_liquidity);
