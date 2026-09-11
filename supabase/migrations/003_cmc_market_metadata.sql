-- Add optional CoinMarketCap ranking and supply context.
-- Apply after 002_market_financial_metrics.sql.
-- These fields enrich exact-address matches only; CMC symbols are never used
-- to identify a market.

alter table public.market_candidates
  add column if not exists cmc_id bigint,
  add column if not exists cmc_slug text,
  add column if not exists cmc_rank integer,
  add column if not exists circulating_supply double precision,
  add column if not exists total_supply double precision,
  add column if not exists cmc_percent_change_7d double precision,
  add column if not exists cmc_volume_change_24h double precision,
  add column if not exists market_cap_dominance double precision;

create index if not exists market_candidates_cmc_rank_idx
  on public.market_candidates (cmc_rank);
