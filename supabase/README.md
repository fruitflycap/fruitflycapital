# Supabase market cache

Fruit Fly Capital uses Supabase as a durable cache for the DexScreener market
universe and the currently locked arena round. This stores identity and
provenance data such as token symbol, name, image URL, links, pair metrics,
market cap, FDV, LP depth, valuation-to-liquidity ratios, and turnover ratios,
and the selected round. It does not turn market data into a fly command.

1. Run [`migrations/001_market_cache.sql`](migrations/001_market_cache.sql) in
   the Supabase SQL editor.
2. Run [`migrations/002_market_financial_metrics.sql`](migrations/002_market_financial_metrics.sql)
   after the first migration.
3. Run [`migrations/003_cmc_market_metadata.sql`](migrations/003_cmc_market_metadata.sql)
   if CoinMarketCap enrichment is enabled.
4. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` on the Python
   backend (Render). The service-role key must never be placed in Vercel or a
   `VITE_*` variable.
5. Set `NEUROSWARM_MARKET_DISCOVERY_ENABLED=true` on the backend and
   `NEUROSWARM_MARKET_WORLD_CAPACITY=100`.
6. Optionally set `CMC_API_KEY` to add CoinMarketCap's ranked listings as an
   additive top-100 context source. CMC rows are matched by exact platform
   chain/address and then resolved through DexScreener; symbols alone never
   create a habitat. Also set `CMC_LISTINGS_LIMIT=100`.
7. Optionally set `NEUROSWARM_MARKET_CACHE_TTL_SECONDS` for the provider's
   refresh interval. The active round is served from Supabase after a backend
   restart until it expires.

## Execution intent queue

Run [`migrations/004_execution_intents.sql`](migrations/004_execution_intents.sql)
in the Supabase SQL editor to create the durable buy/sell queue. It stores the
netted execution payload, fly IDs, token identity, processing status, retries,
worker lease, result, and error for every intent. The queue is server-only;
keep `SUPABASE_SERVICE_ROLE_KEY` on Render and never in the frontend.

Run [`migrations/005_behavior_proposals.sql`](migrations/005_behavior_proposals.sql)
after migration 004. The brain service writes every biological BUY/SELL
proposal immediately to the same table with `status = 'observed'` and
`execution_eligible = false`, so the behavior log is durable and shared across
viewers. The runtime separately writes the netted, amount-bearing execution
row with `status = 'pending'`; only those rows are claimed by the trade worker.
This keeps an audit of every fly signal without allowing a zero-amount display
record to become a swap.

On the Render brain service, set:

```env
FUND_ADAPTER=supabase
FUND_INTENT_QUEUE_BACKEND=supabase
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only-key>
```

On the Render Background Worker, run:

```bash
PYTHONPATH=src python scripts/run_trade_executor.py --backend supabase --mode prepare
```

The worker claims rows atomically through `claim_execution_intents`, so a
restart or a second worker cannot process the same pending row concurrently.
Only change the worker to `--mode broadcast` after prepared transactions have
been reviewed and the wallet/risk settings have been verified.

`SUPABASE_ANON_KEY` is accepted for read attempts, but writes require the
service-role key. With no Supabase variables, the application continues to use
its existing in-process cache and does not fail startup.
