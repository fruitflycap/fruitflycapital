import json

from malecns.fund.chain_client import ChainBalance, FakeChainClient
from malecns.fund.execution import ExecutionEngine, FakeExecutionAdapter
from malecns.fund.ledger import FundLedger
from malecns.fund.models import TradeIntent
from malecns.fund.portfolio import PortfolioEngine
from malecns.fund.privy_client import FakePrivyClient, PrivyConfig
from malecns.fund.nav_reporter import FundNavReporter
from malecns.fund.valuation import FakeValuationProvider
from malecns.fund.wallet import RpcWalletClient, WalletSnapshot
from malecns.fund.autonomous import AutonomousTradingRuntime, ExecutionIntent, QueueExecutionAdapter, SimulationExecutionAdapter, SupabaseExecutionAdapter, TokenRef
from malecns.fund.supabase_queue import SupabaseIntentQueue
from malecns.fund.receipts import BlockscoutClient, ReceiptStatus, observe_receipt
from malecns.swarm.observer import BehaviorTradeIntent


def test_ledger_deduplicates_external_events_and_records_trade():
    ledger = FundLedger(":memory:")
    assert ledger.append_event("Deposit", {"amount": 100}, source="vault", external_id="0x1")
    assert ledger.append_event("Deposit", {"amount": 100}, source="vault", external_id="0x1") is None
    ledger.record_trade({"chain_id": 84532, "token_in": "USDC", "token_out": "TOKEN", "amount_in": "5", "round_id": "12", "neuroswarm_decision_id": "d1"})
    assert ledger.rows("trades")[0]["round_id"] == "12"


def test_portfolio_is_chain_aware_and_reconciles():
    ledger = FundLedger(":memory:")
    ledger.record_deposit(asset="USDC", amount=100, shares=100)
    ledger.upsert_position(chain_id=84532, token_address="0xabc", symbol="USDC", amount=100, cost_basis_usd=100)
    ledger.upsert_position(chain_id=1, token_address="0xabc", symbol="USDC", amount=2, cost_basis_usd=2)
    prices = FakeValuationProvider({(84532, "0xabc"): 1, (1, "0xabc"): 1})
    snapshot = PortfolioEngine(ledger, prices).snapshot()
    assert snapshot.nav_usd == 102
    assert len(snapshot.positions) == 2
    assert PortfolioEngine(ledger, prices).reconcile({(84532, "0xabc"): 100}, {(84532, "0xabc"): 99})["status"] == "discrepancy"


def test_dry_run_never_calls_execution_adapter_and_live_is_gated():
    adapter = FakeExecutionAdapter()
    intent = TradeIntent("token", "buy", "USDC", "TOKEN", "5", 84532, .1, .8, "test")
    dry = ExecutionEngine("dry-run", adapter=adapter).execute(intent)
    assert dry.status == "proposal_only" and not adapter.calls
    live = ExecutionEngine("live", adapter=adapter, live_confirmed=False).execute(intent, explicit_confirmation=True)
    assert live.status == "blocked" and not adapter.calls
    testnet = ExecutionEngine("testnet", adapter=adapter).execute(intent)
    assert testnet.status == "simulated" and len(adapter.calls) == 1


def test_fake_chain_client_does_not_merge_same_address_across_chains():
    items = [ChainBalance(1, "0xwallet", "0xasset", 1), ChainBalance(84532, "0xwallet", "0xasset", 2)]
    client = FakeChainClient(items)
    assert [x.amount for x in client.get_balances(1, "0xwallet", ["0xasset"])] == [1]
    assert PrivyConfig(app_id="a", app_secret="b").configured


def test_buy_and_partial_sell_update_cost_basis_and_realized_pnl():
    ledger = FundLedger(":memory:")
    engine = PortfolioEngine(ledger, FakeValuationProvider())
    engine.apply_trade(chain_id=84532, token_in="USDC", token_out="TOKEN", amount_in=10, amount_out=100, usd_value=10, symbol_out="TOKEN")
    realized = engine.apply_trade(chain_id=84532, token_in="TOKEN", token_out="USDC", amount_in=40, amount_out=6, usd_value=6, symbol_out="USDC")
    ledger.record_trade({"chain_id": 84532, "token_in": "TOKEN", "token_out": "USDC", "amount_in": "40", "amount_out": "6", "usd_value": 6, "realized_pnl_usd": realized, "status": "filled"})
    token = next(row for row in ledger.rows("positions", limit=10) if row["token_address"] == "TOKEN")
    assert token["amount"] == 60 and token["cost_basis_usd"] == 6
    assert realized == 2
    assert engine.snapshot().realized_pnl_usd == 2


def test_nav_reporting_and_privy_fake_are_explicitly_gated():
    reporter = FundNavReporter("dry-run")
    assert reporter.report(55).status == "preview"
    assert reporter.report(55, explicit_confirmation=False).status == "preview"
    privy = FakePrivyClient()
    try:
        privy.send_transaction("fake-wallet", {"to": "0x1"}, caip2="eip155:84532")
    except PermissionError:
        pass
    else:
        raise AssertionError("fake Privy client must require confirmation")


def test_wallet_snapshot_keeps_gas_reserve_out_of_tradeable_balance():
    snapshot = WalletSnapshot(4663, "0xB2B6710B85BfFF84b68aA4a91e78532f4FA726a9", 4_500_000_000_000_000)
    assert float(snapshot.native_balance_eth) == 0.0045
    assert snapshot.available_native_wei == 2_500_000_000_000_000
    assert snapshot.as_dict()["availableToTrade"] == 0.0025


def test_rpc_wallet_rejects_chain_mismatch_without_signing():
    client = RpcWalletClient("https://example.invalid", "0xB2B6710B85BfFF84b68aA4a91e78532f4FA726a9", expected_chain_id=4663)
    client.call = lambda method, params: "0xb626" if method == "eth_chainId" else "0x0"  # type: ignore[method-assign]
    try:
        client.snapshot()
    except RuntimeError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("wallet must reject an RPC on the wrong chain")


def test_autonomous_runtime_assigns_one_sixteenth_and_debounces_departure():
    ledger = FundLedger(":memory:")
    wallet = RpcWalletClient("https://example.invalid", "0xB2B6710B85BfFF84b68aA4a91e78532f4FA726a9", expected_chain_id=4663)
    wallet.call = lambda method, params: "0x1237" if method == "eth_chainId" else "0x0" if method == "eth_getBalance" else "0x0"  # type: ignore[method-assign]
    wallet.snapshot = lambda: WalletSnapshot(4663, wallet.wallet_address, 4_500_000_000_000_000)  # type: ignore[method-assign]
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, wallet=wallet, adapter=SimulationExecutionAdapter(), departure_debounce_ms=1_500, min_hold_seconds=0)
    token = "0x1111111111111111111111111111111111111111"
    runtime.update_habitats([{"id": "market-1", "label": "MARKET", "chainId": "robinhood", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 2.0}, {"name": "market.priceUsd", "value": 4.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    buy = BehaviorTradeIntent("buy-1", "fly-001", "market-1", "buy", "dwell", .9, 1000, {"contact": True}, .0625)
    after_buy = runtime.ingest([buy], observed_at_ms=1000)
    assert after_buy["perFlyAllocationPercent"] == 6.25
    assert after_buy["flies"][0]["state"] == "HOLDING"
    sell = BehaviorTradeIntent("sell-1", "fly-001", "market-1", "sell", "departure", .9, 2000, {"contact": False}, .0625)
    assert runtime.ingest([sell], observed_at_ms=2000)["flies"][0]["state"] == "DEPARTING"
    assert runtime.ingest([], observed_at_ms=3000)["flies"][0]["state"] == "DEPARTING"
    assert runtime.ingest([], observed_at_ms=4000)["flies"][0]["state"] == "EXPLORING"
    assert ledger.rows("execution_attempts")[0]["status"] == "filled"


def test_autonomous_return_uses_entry_cost_basis_and_latest_token_value():
    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=8, min_hold_seconds=0, adapter=SimulationExecutionAdapter())
    token = "0x6666666666666666666666666666666666666666"
    runtime.update_habitats([{"id": "market-return", "label": "RETURN", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 2.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    runtime.ingest([BehaviorTradeIntent("return-buy", "fly-001", "market-return", "buy", "dwell", .9, 1000, {"contact": True}, .0625)], observed_at_ms=1000)

    runtime.update_habitats([{"id": "market-return", "label": "RETURN", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 3.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    snapshot = runtime.snapshot(observed_at_ms=2000)

    assert snapshot["portfolioCostBasisUsd"] > 0
    assert snapshot["portfolioMarkedValueUsd"] > snapshot["portfolioCostBasisUsd"]
    assert snapshot["portfolioReturnPct"] == 50.0


def test_autonomous_runtime_enforces_two_minute_minimum_hold_before_sell():
    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=SimulationExecutionAdapter(), departure_debounce_ms=1_500)
    token = "0x4444444444444444444444444444444444444444"
    runtime.update_habitats([{"id": "market-4", "label": "MARKET", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 2.0}, {"name": "market.priceUsd", "value": 4.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    runtime.ingest([BehaviorTradeIntent("buy-2", "fly-001", "market-4", "buy", "dwell", .9, 1_000, {"contact": True}, .0625)], observed_at_ms=1_000)
    runtime.ingest([BehaviorTradeIntent("sell-2", "fly-001", "market-4", "sell", "departure", .9, 2_000, {"contact": False}, .0625)], observed_at_ms=2_000)

    early = runtime.ingest([], observed_at_ms=120_999)
    assert early["flies"][0]["state"] == "DEPARTING"
    assert not any(row["status"] == "filled" and row["side"] == "sell" for row in ledger.rows("execution_attempts"))

    released = runtime.ingest([], observed_at_ms=121_000)
    assert released["flies"][0]["state"] == "EXPLORING"
    assert any(row["status"] == "filled" and row["side"] == "sell" for row in ledger.rows("execution_attempts"))


def test_unfilled_buy_does_not_open_another_buy_slot_for_same_fly():
    class PreparedAdapter:
        def execute(self, intent, token):
            return {"status": "prepared_external_authorization"}

    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=8, adapter=PreparedAdapter())
    first_token = "0x1111111111111111111111111111111111111111"
    second_token = "0x2222222222222222222222222222222222222222"
    runtime.update_habitats([
        {"id": "market-first", "label": "FIRST", "chainId": "4663", "tokenAddress": first_token},
        {"id": "market-second", "label": "SECOND", "chainId": "4663", "tokenAddress": second_token},
    ])
    runtime.ingest([BehaviorTradeIntent("pending-buy-1", "fly-001", "market-first", "buy", "dwell", .9, 1000, {}, .0625)], observed_at_ms=1000)
    snapshot = runtime.ingest([BehaviorTradeIntent("pending-buy-2", "fly-001", "market-second", "buy", "dwell", .9, 2000, {}, .0625)], observed_at_ms=2000)

    assert len(ledger.rows("execution_attempts")) == 1
    assert snapshot["flies"][0]["state"] == "QUALIFYING"
    assert snapshot["events"][-1]["type"] == "PENDING"


def test_prepared_external_execution_never_becomes_a_fill():
    class PreparedAdapter:
        def execute(self, intent, token):
            return {"status": "prepared_external_authorization", "nonce": "0x2a", "estimatedGas": "0x5208"}

    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=PreparedAdapter())
    token = "0x2222222222222222222222222222222222222222"
    runtime.update_habitats([{"id": "market-2", "label": "MARKET", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 1.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    buy = BehaviorTradeIntent("prepared-1", "fly-001", "market-2", "buy", "dwell", .9, 1000, {"contact": True}, .0625)
    snapshot = runtime.ingest([buy], observed_at_ms=1000)
    assert snapshot["flies"][0]["state"] == "QUALIFYING"
    assert snapshot["pendingRebalance"][0]["status"] == "prepared_external_authorization"
    assert ledger.rows("execution_attempts")[0]["nonce"] == "0x2a"


def test_queue_adapter_publishes_one_netted_intent_for_the_executor(tmp_path):
    ledger = FundLedger(":memory:")
    queue_path = tmp_path / "execution-intents.jsonl"
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=QueueExecutionAdapter(queue_path), min_hold_seconds=0)
    token = "0x5555555555555555555555555555555555555555"
    runtime.update_habitats([{"id": "market-queue", "label": "AERO", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 1.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    intents = [
        BehaviorTradeIntent("queue-1", "fly-001", "market-queue", "buy", "dwell", .9, 1000, {"contact": True}, .0625),
        BehaviorTradeIntent("queue-2", "fly-002", "market-queue", "buy", "dwell", .9, 1000, {"contact": True}, .0625),
    ]
    runtime.ingest(intents, observed_at_ms=1000)
    records = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["executionIntent"]["side"] == "buy"
    assert records[0]["executionIntent"]["flyIds"] == ["fly-001", "fly-002"]
    assert ledger.rows("execution_attempts")[0]["status"] == "queued"


def test_supabase_queue_records_each_behavior_proposal_as_observed(monkeypatch):
    requests = []

    class RecordingQueue(SupabaseIntentQueue):
        def _request(self, method, path, body=None, query="", prefer=None):
            requests.append({"method": method, "path": path, "body": body, "query": query, "prefer": prefer})
            return None

    monkeypatch.setenv("FUND_CHAIN_ID", "4663")
    queue = RecordingQueue("https://example.supabase.co", "service-role")
    queue.record_behavior_proposal(
        {
            "intentId": "bio-buy-1",
            "flyId": "fly-001",
            "habitatId": "habitat-1",
            "side": "buy",
            "reason": "dwell",
            "confidence": 0.8,
        },
        {"chainId": 4663, "address": "0x1111111111111111111111111111111111111111", "symbol": "FLY"},
    )
    queue.record_behavior_proposal(
        {
            "intentId": "bio-sell-1",
            "flyId": "fly-002",
            "habitatId": "habitat-1",
            "side": "sell",
            "reason": "departure",
            "confidence": 0.7,
        },
        {"chainId": 4663, "address": "0x1111111111111111111111111111111111111111", "symbol": "FLY"},
    )

    assert len(requests) == 2
    buy, sell = (request["body"][0] for request in requests)
    assert buy["status"] == "observed"
    assert buy["execution_eligible"] is False
    assert buy["behavior_intent_id"] == "bio-buy-1"
    assert buy["token_in"] == "0x0000000000000000000000000000000000000000"
    assert buy["token_out"].lower() == "0x1111111111111111111111111111111111111111"
    assert sell["token_in"].lower() == "0x1111111111111111111111111111111111111111"
    assert sell["token_out"] == "0x0000000000000000000000000000000000000000"


def test_supabase_runtime_records_behavior_and_netted_execution(monkeypatch):
    class RecordingQueue:
        def __init__(self):
            self.behaviors = []
            self.executions = []

        def record_behavior_proposal(self, behavior, token):
            self.behaviors.append((behavior, token))

        def enqueue(self, payload):
            self.executions.append(payload)

    monkeypatch.setenv("FUND_CHAIN_ID", "4663")
    queue = RecordingQueue()
    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=SupabaseExecutionAdapter(queue), min_hold_seconds=0)
    token = "0x2222222222222222222222222222222222222222"
    runtime.update_habitats([{"id": "market-supabase", "label": "FLY", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 1.0}]}])
    runtime.ingest(
        [
            BehaviorTradeIntent("bio-buy-a", "fly-001", "market-supabase", "buy", "dwell", 0.8, 1000, {}, 0.0625),
            BehaviorTradeIntent("bio-buy-b", "fly-002", "market-supabase", "buy", "dwell", 0.8, 1000, {}, 0.0625),
        ],
        observed_at_ms=1000,
    )

    assert [behavior["intentId"] for behavior, _token in queue.behaviors] == ["bio-buy-a", "bio-buy-b"]
    assert len(queue.executions) == 1
    assert queue.executions[0]["executionIntent"]["side"] == "buy"
    assert queue.executions[0]["executionIntent"]["flyIds"] == ["fly-001", "fly-002"]


def test_supabase_runtime_imports_real_executor_results_for_shared_ui():
    token = "0x2222222222222222222222222222222222222222"
    tx_hash = "0x" + "a" * 64

    class ResultQueue:
        def execution_results(self, limit=100):
            return [{
                "idempotency_key": "execution-1",
                "side": "buy",
                "chain_id": 4663,
                "token_in": "0x0000000000000000000000000000000000000000",
                "token_out": token,
                "amount_in": "156250000000000",
                "fly_ids": ["fly-007"],
                "biological_event_id": "bio-1",
                "payload": {"token": {"address": token, "symbol": "AERO", "priceUsd": 1.0}},
                "status": "confirmed",
                "result": {"status": "CONFIRMED", "txHash": tx_hash, "expectedOutput": "123"},
            }]

    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=SupabaseExecutionAdapter(ResultQueue()))
    snapshot = runtime.snapshot(observed_at_ms=1000)
    assert snapshot["mainnetExecutions"][0]["txHash"] == tx_hash
    assert snapshot["mainnetExecutions"][0]["status"] == ReceiptStatus.BROADCAST
    assert snapshot["mainnetExecutions"][0]["flyIds"] == ["fly-007"]


def test_mainnet_receipt_uses_rpc_as_canonical_and_enriches_with_blockscout():
    wallet_address = "0xB2B6710B85BfFF84b68aA4a91e78532f4FA726a9"
    token_address = "0x1111111111111111111111111111111111111111"
    recipient_topic = "0x" + ("0" * 24) + wallet_address[2:].lower()
    token_topic = "0x" + ("0" * 24) + wallet_address[2:].lower()
    receipt = {
        "status": "0x1",
        "blockNumber": "0x5a00001",
        "transactionIndex": "0x2",
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x3b9aca00",
        "logs": [{"address": token_address, "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", token_topic, recipient_topic], "data": "0x2b5e3af16b1880000"}],
    }
    class ReceiptWallet:
        def __init__(self):
            self.wallet_address = wallet_address

        def call(self, method, params):
            if method == "eth_getTransactionReceipt":
                return receipt
            if method == "eth_getTransactionByHash":
                return {"from": wallet_address, "to": "0x2222222222222222222222222222222222222222", "value": "0x38d7ea4c68000"}
            raise AssertionError(method)

    seen_urls = []
    blockscout = BlockscoutClient(fetcher=lambda url, timeout: seen_urls.append(url) or {"status": "ok", "method": "swap"})
    observation = observe_receipt(ReceiptWallet(), "0x" + "a" * 64, side="buy", token_address=token_address, token_symbol="AERO", input_token="0x0000000000000000000000000000000000000000", input_amount="1000000000000000", blockscout=blockscout, output_decimals=18)
    assert observation.status == ReceiptStatus.CONFIRMED
    assert observation.block_number == 94371841
    assert observation.transaction_fee == str(21000 * 1_000_000_000)
    assert observation.actual_output_amount == "50"
    assert observation.blockscout == {"status": "ok", "method": "swap"}
    assert seen_urls == ["https://robinhoodchain.blockscout.com/api/v2/transactions/0x" + "a" * 64]


def test_external_broadcast_registration_keeps_simulation_hashes_out_of_mainnet():
    class PreparedAdapter:
        def execute(self, intent, token):
            return {"status": "prepared_external_authorization", "nonce": "0x2a"}

    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16, adapter=PreparedAdapter())
    token = "0x3333333333333333333333333333333333333333"
    runtime.update_habitats([{"id": "market-3", "label": "AERO", "chainId": "4663", "tokenAddress": token, "signals": [{"name": "market.priceNative", "value": 1.0}, {"name": "market.priceUsd", "value": 1.0}, {"name": "liquidity.usd", "value": 100000.0}]}])
    snapshot = runtime.ingest([BehaviorTradeIntent("bio-1", "fly-007", "market-3", "buy", "dwell", .9, 1000, {"contact": True}, .0625)], observed_at_ms=1000)
    execution_id = ledger.rows("execution_attempts")[0]["execution_id"] if "execution_id" in ledger.rows("execution_attempts")[0] else ledger.rows("execution_attempts")[0]["idempotency_key"]
    assert runtime.register_broadcast(execution_id, "0x" + "b" * 64, expected_output="123.45", biological_event_id="bio-1")
    execution = ledger.rows("mainnet_executions")[0]
    assert execution["status"] == ReceiptStatus.BROADCAST
    assert execution["chain_id"] == 4663
    assert execution["tx_hash"] == "0x" + "b" * 64
    assert not any(str(event.get("tx_hash", "")).startswith("0xsim") for event in ledger.rows("mainnet_executions"))


def test_direct_broadcast_record_does_not_depend_on_ledger_lookup():
    ledger = FundLedger(":memory:")
    runtime = AutonomousTradingRuntime(ledger, expected_agents=16)
    token = TokenRef(4663, "0x4444444444444444444444444444444444444444", "AERO")
    intent = ExecutionIntent(
        "execution-direct",
        "buy",
        4663,
        "0x0000000000000000000000000000000000000000",
        token.address,
        "156250000000000",
        ("fly-007",),
        0.5,
        1000,
        "bio-direct",
    )

    runtime.record_broadcast(intent, token, "0x" + "c" * 64, expected_output="123")
    execution = ledger.rows("mainnet_executions")[0]
    assert execution["tx_hash"] == "0x" + "c" * 64
    assert execution["status"] == ReceiptStatus.BROADCAST
