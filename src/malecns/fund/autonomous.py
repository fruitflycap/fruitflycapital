"""Autonomous fly allocation, netting, accounting, and execution adapters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol

from malecns.swarm.observer import BehaviorTradeIntent

from ..market.direct_uniswap import DirectUniswapClient
from ..market.uniswap_client import UniswapTradingClient
from .ledger import FundLedger
from .receipts import BlockscoutClient, ReceiptStatus, explorer_url, observe_receipt
from .wallet import ZERO_ADDRESS, RpcWalletClient, WalletRpcError
from .supabase_queue import SupabaseIntentQueue


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class FlyBehaviorState(str, Enum):
    EXPLORING = "EXPLORING"
    APPROACHING = "APPROACHING"
    QUALIFYING = "QUALIFYING"
    HOLDING = "HOLDING"
    DEPARTING = "DEPARTING"


@dataclass(frozen=True)
class TokenRef:
    chain_id: int
    address: str
    symbol: str
    liquidity_usd: float | None = None
    price_usd: float | None = None
    price_native: float | None = None

    @classmethod
    def from_habitat(cls, habitat: Mapping[str, Any]) -> "TokenRef | None":
        address = str(habitat.get("tokenAddress") or "").strip()
        if not ADDRESS_RE.fullmatch(address):
            return None
        chain = str(habitat.get("chainId") or "robinhood").lower()
        chain_id = int(os.getenv("FUND_CHAIN_ID", "4663")) if chain == "robinhood" else int(chain)
        values: dict[str, Any] = {}
        for signal in habitat.get("signals") or ():
            if isinstance(signal, Mapping) and signal.get("name"):
                values[str(signal["name"])] = signal.get("value")
        return cls(
            chain_id,
            address,
            str(habitat.get("label") or address[:8]),
            _number(values.get("liquidity.usd")),
            _number(values.get("market.priceUsd")),
            _number(values.get("market.priceNative")),
        )


@dataclass(frozen=True)
class FlyCapitalPosition:
    fly_id: str
    state: str = FlyBehaviorState.EXPLORING.value
    chain_id: int | None = None
    token_address: str | None = None
    token_symbol: str | None = None
    allocation_fraction: float = 0.0625
    entry_timestamp_ms: int | None = None
    entry_price_usd: float | None = None
    held_amount: float = 0.0
    current_value_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    departure_reason: str | None = None
    updated_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "flyId": self.fly_id,
            "state": self.state,
            "chainId": self.chain_id,
            "tokenAddress": self.token_address,
            "tokenSymbol": self.token_symbol,
            "allocationFraction": self.allocation_fraction,
            "allocationPercent": self.allocation_fraction * 100.0,
            "entryTimestampMs": self.entry_timestamp_ms,
            "entryPriceUsd": self.entry_price_usd,
            "heldAmount": self.held_amount,
            "currentValueUsd": self.current_value_usd,
            "realizedPnlUsd": self.realized_pnl_usd,
            "unrealizedPnlUsd": self.unrealized_pnl_usd,
            "departureReason": self.departure_reason,
            "updatedMs": self.updated_ms,
        }

    def ledger_dict(self) -> dict[str, Any]:
        return {
            "fly_id": self.fly_id,
            "state": self.state,
            "chain_id": self.chain_id,
            "token_address": self.token_address,
            "token_symbol": self.token_symbol,
            "allocation_fraction": self.allocation_fraction,
            "entry_timestamp_ms": self.entry_timestamp_ms,
            "entry_price_usd": self.entry_price_usd,
            "held_amount": self.held_amount,
            "current_value_usd": self.current_value_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "unrealized_pnl_usd": self.unrealized_pnl_usd,
            "departure_reason": self.departure_reason,
            "updated_ms": self.updated_ms,
        }


@dataclass(frozen=True)
class AllocationIntent:
    """The biology-owned allocation decision for one primary CNS fly."""

    fly_id: str
    side: str
    token: TokenRef
    allocation_fraction: float
    reason: str
    observed_at_ms: int
    biological_event_id: str | None = None


@dataclass(frozen=True)
class PortfolioDelta:
    """A netted portfolio change produced after allocation decisions."""

    side: str
    token: TokenRef
    fly_ids: tuple[str, ...]
    amount_in: int
    token_in: str
    token_out: str
    reason: str
    biological_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketRiskGuard:
    """Market/execution checks kept independent from fly behavior."""

    min_liquidity_usd: float = 0.0

    def reject_reason(self, token: TokenRef) -> str | None:
        if token.liquidity_usd is None or token.liquidity_usd < self.min_liquidity_usd:
            return "minimum liquidity"
        return None


@dataclass(frozen=True)
class ExecutionIntent:
    idempotency_key: str
    side: str
    chain_id: int
    token_in: str
    token_out: str
    amount_in: str
    fly_ids: tuple[str, ...]
    slippage_tolerance: float
    created_at_ms: int
    biological_event_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "idempotencyKey": self.idempotency_key,
            "side": self.side,
            "chainId": self.chain_id,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "amountIn": self.amount_in,
            "flyIds": list(self.fly_ids),
            "slippageTolerance": self.slippage_tolerance,
            "createdAtMs": self.created_at_ms,
            "biologicalEventId": self.biological_event_id,
        }


class ExecutionAdapter(Protocol):
    def execute(self, intent: ExecutionIntent, token: TokenRef) -> Mapping[str, Any]: ...


class SimulationExecutionAdapter:
    """Fully automatic deterministic adapter for tests and the demo."""

    def execute(self, intent: ExecutionIntent, token: TokenRef) -> Mapping[str, Any]:
        amount = float(intent.amount_in)
        output = amount / max(token.price_native or 1.0, 1e-18)
        digest = hashlib.sha256(intent.idempotency_key.encode()).hexdigest()[:24]
        return {"status": "filled", "txHash": f"0xsim{digest}", "amountOut": str(output), "gas": "0", "slippage": 0.0, "executionPrice": token.price_native}


class MainnetExecutionAdapter:
    """Uniswap quote/transaction preparation adapter.

    It validates the external transaction boundary and returns a ready-to-sign
    transaction. Broadcasting remains owned by the platform authorization
    boundary and is intentionally not performed here.
    """

    def __init__(self, wallet: RpcWalletClient, client: DirectUniswapClient | UniswapTradingClient) -> None:
        self.wallet = wallet
        self.client = client

    def execute(self, intent: ExecutionIntent, token: TokenRef) -> Mapping[str, Any]:
        wallet = self.wallet.snapshot()
        if wallet.chain_id != intent.chain_id:
            raise WalletRpcError("execution chain does not match wallet RPC chain")
        if intent.token_in.lower() == ZERO_ADDRESS.lower() and int(intent.amount_in) > wallet.available_native_wei:
            raise WalletRpcError("insufficient native balance after gas reserve")
        amount_in = int(intent.amount_in)
        if isinstance(self.client, UniswapTradingClient):
            if intent.token_in.lower() != ZERO_ADDRESS.lower():
                approval_response = self.client.check_approval_for_swap(wallet_address=wallet.wallet_address, token=intent.token_in, amount=amount_in, chain_id=intent.chain_id)
                cancel = approval_response.get("cancel")
                approval = approval_response.get("approval")
                if isinstance(cancel, Mapping):
                    return {"status": "approval_cancel_required", "approval": {"transaction": cancel, "source": "uniswap-trading-api"}, "txHash": None}
                if isinstance(approval, Mapping):
                    return {"status": "approval_required", "approval": {"transaction": approval, "source": "uniswap-trading-api"}, "txHash": None}
            quote = self.client.quote_exact_input(swapper=wallet.wallet_address, token_in=intent.token_in, token_out=intent.token_out, chain_id=intent.chain_id, amount_in=amount_in, slippage_tolerance=intent.slippage_tolerance)
            tx = self.client.create_swap_transaction(quote)
            if tx.get("from") and str(tx["from"]).lower() != wallet.wallet_address.lower():
                raise WalletRpcError("Uniswap API transaction sender does not match the strategy wallet")
            if tx.get("chainId") is not None and int(tx["chainId"]) != wallet.chain_id:
                raise WalletRpcError("Uniswap API transaction chain does not match the wallet RPC chain")
            if not isinstance(tx.get("to"), str) or not ADDRESS_RE.fullmatch(str(tx.get("to"))) or not isinstance(tx.get("data"), str) or tx.get("data") in {"", "0x"} or tx.get("value") is None:
                raise WalletRpcError("Uniswap API returned invalid transaction calldata")
            try:
                estimated_gas = self.wallet.call("eth_estimateGas", [{"from": wallet.wallet_address, "to": tx["to"], "data": tx["data"], "value": hex(int(str(tx["value"]), 16) if str(tx["value"]).startswith("0x") else int(str(tx["value"])))}, "latest"])
            except Exception as exc:
                raise WalletRpcError(f"gas estimation failed: {exc}") from exc
            nonce = self.wallet.call("eth_getTransactionCount", [wallet.wallet_address, "pending"])
            return {"status": "prepared_external_authorization", "txHash": None, "quote": quote.as_dict(), "swap": tx, "nonce": nonce, "estimatedGas": estimated_gas, "executionPrice": token.price_native, "gas": None, "slippage": intent.slippage_tolerance}
        quote = self.client.quote(token_in=intent.token_in, token_out=intent.token_out, amount_in=amount_in)
        if intent.token_in.lower() != ZERO_ADDRESS.lower():
            allowance = self.client.allowance(intent.token_in, wallet.wallet_address, route_kind=quote.kind)
            if allowance < amount_in:
                approval = self.client.approval_transaction(intent.token_in, amount_in, route_kind=quote.kind)
                return {"status": "approval_required", "approval": {"transaction": approval, "source": "onchain-rpc"}, "txHash": None}
        tx = self.client.build_swap(quote, recipient=wallet.wallet_address, slippage_tolerance=intent.slippage_tolerance)
        if not isinstance(tx.get("to"), str) or not ADDRESS_RE.fullmatch(str(tx.get("to"))) or not isinstance(tx.get("data"), str) or tx.get("data") in {"", "0x"} or tx.get("value") is None:
            raise WalletRpcError("direct Uniswap route returned invalid transaction calldata")
        try:
            estimated_gas = self.wallet.call("eth_estimateGas", [{"from": wallet.wallet_address, "to": tx["to"], "data": tx["data"], "value": str(tx["value"])}, "latest"])
        except Exception as exc:
            raise WalletRpcError(f"gas estimation failed: {exc}") from exc
        nonce = self.wallet.call("eth_getTransactionCount", [wallet.wallet_address, "pending"])
        return {"status": "prepared_external_authorization", "txHash": None, "quote": quote.as_dict(), "swap": tx, "nonce": nonce, "estimatedGas": estimated_gas, "executionPrice": token.price_native, "gas": None, "slippage": intent.slippage_tolerance}


class QueueExecutionAdapter:
    """Publish execution intents for a separately run trade executor."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = str(path)

    def execute(self, intent: ExecutionIntent, token: TokenRef) -> Mapping[str, Any]:
        payload = {
            "executionIntent": intent.as_dict(),
            "token": {
                "chainId": token.chain_id,
                "address": token.address,
                "symbol": token.symbol,
                "liquidityUsd": token.liquidity_usd,
                "priceUsd": token.price_usd,
                "priceNative": token.price_native,
            },
            "queuedAtMs": int(time.time() * 1000),
        }
        queue_path = os.path.abspath(self.path)
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()
        return {"status": "queued", "txHash": None, "queuePath": queue_path}


class SupabaseExecutionAdapter:
    """Publish execution intents to the shared Supabase queue."""

    def __init__(self, queue: SupabaseIntentQueue) -> None:
        self.queue = queue

    def record_behavior_proposal(self, behavior: BehaviorTradeIntent, token: TokenRef | None) -> None:
        token_payload = None
        if token is not None:
            token_payload = {
                "chainId": token.chain_id,
                "address": token.address,
                "symbol": token.symbol,
                "liquidityUsd": token.liquidity_usd,
                "priceUsd": token.price_usd,
                "priceNative": token.price_native,
            }
        self.queue.record_behavior_proposal(behavior.as_dict(), token_payload)

    def execute(self, intent: ExecutionIntent, token: TokenRef) -> Mapping[str, Any]:
        payload = {
            "executionIntent": intent.as_dict(),
            "token": {
                "chainId": token.chain_id,
                "address": token.address,
                "symbol": token.symbol,
                "liquidityUsd": token.liquidity_usd,
                "priceUsd": token.price_usd,
                "priceNative": token.price_native,
            },
            "queuedAtMs": int(time.time() * 1000),
        }
        self.queue.enqueue(payload)
        return {"status": "queued", "txHash": None, "queueBackend": "supabase"}


class AutonomousTradingRuntime:
    """Stateful fly allocation runtime with netted execution intents."""

    def __init__(self, ledger: FundLedger, *, expected_agents: int = 8, wallet: RpcWalletClient | None = None, adapter: ExecutionAdapter | None = None, departure_debounce_ms: int = 1_500, min_hold_seconds: float = 120.0, min_liquidity_usd: float = 0.0, slippage_tolerance: float = 0.5, max_per_fly_allocation_fraction: float = 0.0625) -> None:
        self.ledger = ledger
        self.expected_agents = max(1, int(expected_agents))
        # Preserve the former sixteen-brain capital ceiling after reducing
        # the active population: eight brains still max out at 6.25% each.
        self.max_per_fly_allocation_fraction = max(0.0, min(1.0, float(max_per_fly_allocation_fraction)))
        self.per_fly_allocation_fraction = min(1.0 / self.expected_agents, self.max_per_fly_allocation_fraction)
        self.wallet = wallet
        self.adapter = adapter or SimulationExecutionAdapter()
        self.receipt_poll_seconds = max(0.5, float(os.getenv("FUND_RECEIPT_POLL_SECONDS", "3")))
        self.blockscout = BlockscoutClient.from_env()
        self._last_receipt_poll = 0.0
        self.departure_debounce_ms = max(0, int(departure_debounce_ms))
        self.min_hold_ms = max(0, int(round(float(min_hold_seconds) * 1000)))
        self.min_hold_seconds = self.min_hold_ms / 1000.0
        self.min_liquidity_usd = max(0.0, float(min_liquidity_usd))
        self.risk_guard = MarketRiskGuard(self.min_liquidity_usd)
        # Token selection belongs to the flies. Do not discard a biological
        # BUY/SELL proposal because market metadata is missing or illiquid;
        # every proposal must reach the shared execution queue for audit and
        # attempted execution. Technical transaction checks remain in the
        # executor (address, balance, gas, quote, approval, and signer).
        self.queue_all_proposals = True
        # Keep an intentionally tight upper bound even if an env value is
        # mistyped; this is a market guard, not a biological preference.
        self.slippage_tolerance = min(5.0, max(0.0, float(slippage_tolerance)))
        self.tokens: dict[str, TokenRef] = {}
        self.tokens_by_address: dict[str, TokenRef] = {}
        self.positions: dict[str, FlyCapitalPosition] = {}
        self.pending_departures: dict[str, tuple[int, str, TokenRef]] = {}
        self.pending_rotations: dict[str, tuple[int, TokenRef, str, str | None]] = {}
        self.processed_events = {str(row["idempotency_key"]) for row in self.ledger.rows("execution_attempts", limit=100000)}
        for index in range(1, self.expected_agents + 1):
            fly_id = f"fly-{index:03d}"
            self.positions[fly_id] = FlyCapitalPosition(fly_id, allocation_fraction=self.per_fly_allocation_fraction)
        for row in self.ledger.rows("fly_positions", limit=100000):
            self.positions[str(row["fly_id"])] = FlyCapitalPosition(str(row["fly_id"]), str(row["state"]), row["chain_id"], row["token_address"], row["token_symbol"], float(row["allocation_fraction"]), row["entry_timestamp_ms"], row["entry_price_usd"], float(row.get("held_amount") or 0), float(row["current_value_usd"]), float(row["realized_pnl_usd"]), float(row["unrealized_pnl_usd"]), row["departure_reason"], int(row["updated_ms"]))
        self.events: list[dict[str, Any]] = []
        self.reconciled_failed_execution_ids: set[str] = set()
        # Shared behavioral feed for every connected viewer. The browser may
        # show an event immediately, but this server-owned history is the
        # canonical cross-user source of truth.
        self.behavior_intents: list[BehaviorTradeIntent] = []
        self.pending_rebalance: list[dict[str, Any]] = []

    @classmethod
    def from_env(cls, ledger: FundLedger, wallet: RpcWalletClient | None = None) -> "AutonomousTradingRuntime":
        mode = os.getenv("FUND_ADAPTER", "simulation").lower()
        adapter: ExecutionAdapter = SimulationExecutionAdapter()
        if mode == "mainnet" and wallet is not None:
            api_client = UniswapTradingClient.from_env()
            adapter = MainnetExecutionAdapter(wallet, api_client or DirectUniswapClient.from_env(wallet))
        elif mode == "queue":
            adapter = QueueExecutionAdapter(os.getenv("FUND_INTENT_QUEUE_PATH", "data/fund/execution-intents.jsonl"))
        elif mode == "supabase":
            queue = SupabaseIntentQueue.from_env()
            if queue is None:
                raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for FUND_ADAPTER=supabase")
            adapter = SupabaseExecutionAdapter(queue)
        try:
            expected_agents = int(os.getenv("NEUROSWARM_SWARM_SIZE", "8"))
        except ValueError:
            expected_agents = 8
        return cls(ledger, expected_agents=max(1, min(100, expected_agents)), wallet=wallet, adapter=adapter, departure_debounce_ms=int(os.getenv("FUND_DEPARTURE_DEBOUNCE_MS", "1500")), min_hold_seconds=float(os.getenv("FUND_MIN_HOLD_SECONDS", "120")), min_liquidity_usd=float(os.getenv("FUND_MIN_LIQUIDITY_USD", "0")), slippage_tolerance=float(os.getenv("FUND_SLIPPAGE_TOLERANCE", "0.5")), max_per_fly_allocation_fraction=float(os.getenv("FUND_MAX_PER_FLY_ALLOCATION_FRACTION", "0.0625")))

    def update_habitats(self, habitats: Iterable[Mapping[str, Any]]) -> None:
        for habitat in habitats:
            token = TokenRef.from_habitat(habitat)
            if token is not None:
                self.tokens[str(habitat.get("id"))] = token
                self.tokens_by_address[_token_key(token.chain_id, token.address)] = token
                for fly_id, position in self.positions.items():
                    if self._position_matches_token(position, token) and position.state == FlyBehaviorState.HOLDING.value:
                        current = (token.price_usd or 0.0) * position.held_amount
                        basis = (position.entry_price_usd or 0.0) * position.held_amount
                        self._save(replace(position, current_value_usd=current, unrealized_pnl_usd=current - basis, updated_ms=int(time.time() * 1000)))

    def register_broadcast(self, execution_id: str, tx_hash: str, *, expected_output: str | None = None, biological_event_id: str | None = None, wallet_before_native_wei: int | None = None) -> bool:
        """Attach a real externally-broadcast hash to an existing intent.

        The signer/authorization layer calls this after it has broadcast the
        prepared transaction. This method only records and observes the hash;
        it cannot sign, submit, or create a transaction.
        """
        existing = next((row for row in self.ledger.rows("mainnet_executions", limit=100000) if str(row.get("tx_hash", "")).lower() == str(tx_hash).lower()), None)
        if existing is not None:
            return True
        attempt = next((row for row in self.ledger.rows("execution_attempts", limit=100000) if str(row.get("idempotency_key")) == execution_id or str(row.get("attempt_id")) == execution_id), None)
        configured_chain_id = self.wallet.expected_chain_id if self.wallet is not None and self.wallet.expected_chain_id is not None else int(os.getenv("FUND_CHAIN_ID", "4663"))
        if attempt is None or int(attempt.get("chain_id") or 0) != configured_chain_id or not _is_real_tx_hash(tx_hash):
            return False
        token_address = str(attempt.get("token_out") if str(attempt.get("token_in")).lower() == ZERO_ADDRESS.lower() else attempt.get("token_in") or "")
        token = self.tokens_by_address.get(_token_key(int(attempt["chain_id"]), token_address)) or TokenRef(int(attempt["chain_id"]), token_address, token_address[:8])
        fly_ids = _json_list(attempt.get("fly_ids_json"))
        intent = ExecutionIntent(execution_id, str(attempt["side"]), int(attempt["chain_id"]), str(attempt["token_in"]), str(attempt["token_out"]), str(attempt["amount_in"]), tuple(fly_ids), float(attempt.get("slippage") or self.slippage_tolerance), int(attempt.get("created_ms") or time.time() * 1000))
        self._persist_broadcast(intent, token, tx_hash, expected_output=expected_output, biological_event_id=biological_event_id, wallet_before_native_wei=wallet_before_native_wei)
        return True

    def record_broadcast(self, intent: ExecutionIntent, token: TokenRef, tx_hash: str, *, expected_output: str | None = None, biological_event_id: str | None = None, wallet_before_native_wei: int | None = None) -> None:
        """Persist a hash using the intent already validated by the executor.

        The separate runner already has the complete intent and token context.
        Reconstructing that context by searching a local ledger can fail after
        a process/database restart, so the post-broadcast path uses this
        direct, idempotent writer instead.
        """
        self._persist_broadcast(
            intent,
            token,
            tx_hash,
            expected_output=expected_output,
            biological_event_id=biological_event_id,
            wallet_before_native_wei=wallet_before_native_wei,
        )

    def ingest(self, intents: Iterable[BehaviorTradeIntent], *, observed_at_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(observed_at_ms or time.time() * 1000)
        actions: list[AllocationIntent] = []
        # Reconcile failures before handling a new habitat visit.  Otherwise
        # a failed external BUY can leave a fly in QUALIFYING forever and the
        # next real BUY proposal will be audit-logged but never re-queued.
        self._sync_shared_execution_results()
        self._flush_departures(timestamp, actions)
        for behavior in intents:
            if behavior.intent_id in self.processed_events:
                continue
            self.behavior_intents.append(behavior)
            if len(self.behavior_intents) > 256:
                self.behavior_intents = self.behavior_intents[-256:]
            token = self.tokens.get(behavior.habitat_id)
            if isinstance(self.adapter, SupabaseExecutionAdapter):
                try:
                    self.adapter.record_behavior_proposal(behavior, token)
                except Exception as exc:
                    # The durable execution row remains the source of truth;
                    # a transient audit-write failure must be visible and must
                    # not silently convert into a local-only proposal.
                    self._event(behavior, "QUEUE_ERROR", str(exc))
            if token is None:
                self._event(behavior, "BLOCKED", "token identity unavailable")
                self.processed_events.add(behavior.intent_id)
                continue
            position = self.positions.setdefault(behavior.fly_id, FlyCapitalPosition(behavior.fly_id, allocation_fraction=self.per_fly_allocation_fraction))
            if behavior.side == "buy":
                # A queued external BUY is not a fill. Keep one pending
                # allocation slot per fly so repeated habitat visits cannot
                # create an unbounded stream of buys before the first one is
                # confirmed or rejected by the executor.
                if position.state == FlyBehaviorState.QUALIFYING.value and position.held_amount <= 0:
                    self._event(behavior, "PENDING", "previous buy is awaiting execution")
                    self.processed_events.add(behavior.intent_id)
                    continue
                if self._position_matches_token(position, token) and position.state in {FlyBehaviorState.HOLDING.value, FlyBehaviorState.QUALIFYING.value}:
                    self.pending_departures.pop(behavior.fly_id, None)
                    self.pending_rotations.pop(behavior.fly_id, None)
                    self._save(replace(position, state=FlyBehaviorState.HOLDING.value, updated_ms=timestamp))
                    self._event(behavior, "HOLD", "continued commitment")
                else:
                    if position.token_address and position.held_amount > 0:
                        minimum_hold_until = self._minimum_hold_until(position)
                        if timestamp < minimum_hold_until:
                            self.pending_departures.pop(behavior.fly_id, None)
                            self.pending_rotations[behavior.fly_id] = (minimum_hold_until, token, behavior.reason, behavior.intent_id)
                            self._save(replace(position, state=FlyBehaviorState.HOLDING.value, departure_reason=None, updated_ms=timestamp))
                            self._event(behavior, "ROTATION_DELAYED", f"minimum hold active for {(minimum_hold_until - timestamp) / 1000.0:.1f}s")
                            self.processed_events.add(behavior.intent_id)
                            continue
                        old = self.tokens_by_address.get(_token_key(position.chain_id or token.chain_id, position.token_address)) or TokenRef(position.chain_id or token.chain_id, position.token_address, position.token_symbol or position.token_address[:8])
                        actions.append(AllocationIntent(behavior.fly_id, "sell", old, position.allocation_fraction, "rotation", timestamp, behavior.intent_id))
                    self.pending_departures.pop(behavior.fly_id, None)
                    self._save(replace(position, state=FlyBehaviorState.QUALIFYING.value, updated_ms=timestamp))
                    actions.append(AllocationIntent(behavior.fly_id, "buy", token, position.allocation_fraction, behavior.reason, timestamp, behavior.intent_id))
                self.processed_events.add(behavior.intent_id)
            elif behavior.side == "sell" and self._position_matches_token(position, token) and position.held_amount > 0:
                minimum_hold_until = self._minimum_hold_until(position)
                due = max(timestamp + self.departure_debounce_ms, minimum_hold_until)
                previous = self.pending_departures.get(behavior.fly_id)
                if previous is not None:
                    due = max(due, previous[0])
                self.pending_departures[behavior.fly_id] = (due, behavior.reason, token)
                self.pending_rotations.pop(behavior.fly_id, None)
                self._save(replace(position, state=FlyBehaviorState.DEPARTING.value, departure_reason=behavior.reason, updated_ms=timestamp))
                wait_seconds = max(0.0, (due - timestamp) / 1000.0)
                self._event(behavior, "DEPARTING", f"debounce started; minimum hold remaining {wait_seconds:.1f}s")
                self.processed_events.add(behavior.intent_id)
        self._execute_netted(actions, timestamp)
        return self.snapshot(timestamp)

    def snapshot(self, observed_at_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(observed_at_ms or time.time() * 1000)
        self._sync_shared_execution_results()
        self._poll_mainnet_receipts(timestamp)
        wallet: dict[str, Any] = {"configured": self.wallet is not None}
        if self.wallet is not None:
            try:
                wallet = {"configured": True, **self.wallet.snapshot().as_dict()}
            except Exception as exc:
                wallet = {"configured": True, "status": "error", "error": str(exc)}
        deployable = int(wallet.get("availableToTradeWei") or 0)
        biological: dict[tuple[int, str], float] = {}
        for position in self.positions.values():
            if position.state == FlyBehaviorState.HOLDING.value and position.token_address:
                identity = (position.chain_id or 0, position.token_address)
                biological[identity] = biological.get(identity, 0.0) + position.allocation_fraction
        actual_by_token: dict[str, dict[str, Any]] = {}
        for position in self.positions.values():
            if position.state != FlyBehaviorState.HOLDING.value or not position.token_address:
                continue
            key = f"{position.chain_id}:{position.token_address.lower()}"
            item = actual_by_token.setdefault(key, {"chainId": position.chain_id, "tokenAddress": position.token_address, "tokenSymbol": position.token_symbol, "intendedAmount": 0.0, "intendedValueUsd": 0.0, "flyIds": []})
            item["intendedAmount"] += position.held_amount
            item["intendedValueUsd"] += position.current_value_usd
            item["flyIds"].append(position.fly_id)
        for execution in self.ledger.rows("mainnet_executions", limit=100000):
            token_address = str(execution.get("token_address") or "")
            if not token_address or token_address.lower() == ZERO_ADDRESS.lower():
                continue
            key = f"{execution.get('chain_id')}:{token_address.lower()}"
            item = actual_by_token.setdefault(key, {"chainId": execution.get("chain_id"), "tokenAddress": token_address, "tokenSymbol": execution.get("token_symbol"), "intendedAmount": 0.0, "intendedValueUsd": 0.0, "flyIds": []})
            item["tokenSymbol"] = item.get("tokenSymbol") or execution.get("token_symbol")
        actual = []
        if self.wallet is not None and wallet.get("nativeBalance") is not None:
            actual.append({
                "chainId": wallet.get("chainId"),
                "tokenAddress": ZERO_ADDRESS,
                "tokenSymbol": wallet.get("nativeSymbol", "ETH"),
                "intendedAmount": 0.0,
                "intendedValueUsd": 0.0,
                "observedAmount": wallet.get("nativeBalance"),
                "observedBalanceWei": wallet.get("nativeBalanceWei"),
                "gasReserve": wallet.get("gasReserve"),
                "reconciliation": "reserve-separated",
                "flyIds": [],
            })
        for item in actual_by_token.values():
            token_ref = self.tokens_by_address.get(_token_key(int(item.get("chainId") or os.getenv("FUND_CHAIN_ID", "4663")), str(item.get("tokenAddress") or "")))
            if token_ref is not None and token_ref.price_usd is not None:
                item["priceUsd"] = token_ref.price_usd
            if self.wallet is not None:
                try:
                    decimals = self.wallet.erc20_decimals(item["tokenAddress"])
                    raw = self.wallet.erc20_balance_raw(item["tokenAddress"])
                    observed_amount = raw / (10**decimals)
                    item.update({"observedBalanceRaw": str(raw), "observedDecimals": decimals, "observedAmount": observed_amount, "amountDelta": observed_amount - item["intendedAmount"], "reconciliation": "matched" if abs(observed_amount - item["intendedAmount"]) <= 1e-12 else "discrepancy"})
                    if item.get("priceUsd") is not None:
                        item["observedValueUsd"] = observed_amount * float(item["priceUsd"])
                except Exception as exc:
                    item["observationError"] = str(exc)
            actual.append(item)
        observed_token_positions = [
            item for item in actual
            if str(item.get("tokenAddress") or "").lower() != ZERO_ADDRESS.lower()
            and float(item.get("observedAmount") or 0.0) > 0.0
        ]
        observed_token_value_usd = sum(float(item["observedValueUsd"]) for item in observed_token_positions if item.get("observedValueUsd") is not None)
        mainnet_executions = [_execution_payload(row) for row in self.ledger.rows("mainnet_executions", limit=100)]
        pending_execution = [item for item in mainnet_executions if item["status"] in {ReceiptStatus.BROADCAST, ReceiptStatus.PENDING}]
        # Mark only confirmed biological holdings.  This deliberately uses
        # each fly's recorded entry price and the latest habitat price, so the
        # return is based on purchased position value versus current value;
        # proposals, quotes, and failed attempts never affect it.
        cost_basis_usd = 0.0
        marked_value_usd = 0.0
        realized_pnl_usd = 0.0
        for position in self.positions.values():
            realized_pnl_usd += position.realized_pnl_usd
            if position.state != FlyBehaviorState.HOLDING.value or not position.token_address or position.held_amount <= 0:
                continue
            basis = (position.entry_price_usd or 0.0) * position.held_amount
            token = self.tokens_by_address.get(_token_key(position.chain_id or 0, position.token_address))
            current_price = token.price_usd if token is not None and token.price_usd is not None else position.entry_price_usd
            current = (current_price or 0.0) * position.held_amount
            if basis > 0:
                cost_basis_usd += basis
                marked_value_usd += current
        unrealized_pnl_usd = marked_value_usd - cost_basis_usd
        portfolio_return_pct = (((marked_value_usd + realized_pnl_usd) / cost_basis_usd) - 1.0) * 100.0 if cost_basis_usd > 0 else None
        return {
            "observedAtMs": timestamp,
            "flyCount": self.expected_agents,
            "executionAdapter": type(self.adapter).__name__,
            "executionBoundary": "simulation-fill" if isinstance(self.adapter, SimulationExecutionAdapter) else "transaction-preparation-only",
            "minimumHoldSeconds": self.min_hold_seconds,
            "externalBroadcast": bool(mainnet_executions),
            "perFlyAllocationFraction": self.per_fly_allocation_fraction,
            "perFlyAllocationPercent": self.per_fly_allocation_fraction * 100.0,
            "maxStrategyAllocationFraction": min(1.0, self.per_fly_allocation_fraction * self.expected_agents),
            "perFlyBudgetWei": str(int(deployable * self.per_fly_allocation_fraction)),
            "wallet": wallet,
            "flies": [self.positions[f"fly-{index:03d}"].as_dict() for index in range(1, self.expected_agents + 1)],
            "biologicalTargetPortfolio": [{"chainId": chain_id, "tokenAddress": token, "allocationFraction": fraction, "allocationPercent": fraction * 100.0} for (chain_id, token), fraction in biological.items()],
            "actualWalletPortfolio": actual,
            "observedPositionCount": len(observed_token_positions),
            "observedTokenValueUsd": observed_token_value_usd,
            "portfolioCostBasisUsd": cost_basis_usd,
            "portfolioMarkedValueUsd": marked_value_usd,
            "portfolioRealizedPnlUsd": realized_pnl_usd,
            "portfolioUnrealizedPnlUsd": unrealized_pnl_usd,
            "portfolioReturnPct": portfolio_return_pct,
            "pendingRebalance": list(self.pending_rebalance[-100:]),
            "pendingExecution": pending_execution,
            "mainnetExecutions": mainnet_executions,
            "events": list(self.events[-100:]),
            "behaviorIntents": [intent.as_dict() for intent in self.behavior_intents[-256:]],
        }

    def _sync_shared_execution_results(self) -> None:
        """Import real executor results into the brain service's ledger.

        Supabase is the only shared durable transport between a deployed brain
        server and a separately-run executor. Only rows with a validated real
        transaction hash are imported; observed proposals and failed queue
        rows remain out of MAINNET EXECUTED.
        """

        if not isinstance(self.adapter, SupabaseExecutionAdapter):
            return
        self._reconcile_shared_execution_failures()
        try:
            rows = self.adapter.queue.execution_results()
        except Exception:
            return
        existing = self.ledger.rows("mainnet_executions", limit=100000)
        known_ids = {str(row.get("execution_id")) for row in existing}
        known_hashes = {str(row.get("tx_hash", "")).lower() for row in existing}
        for row in rows:
            result = row.get("result")
            if not isinstance(result, Mapping):
                continue
            tx_hash = str(result.get("txHash") or "")
            if not _is_real_tx_hash(tx_hash) or str(row.get("idempotency_key")) in known_ids or tx_hash.lower() in known_hashes:
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
            raw_token = payload.get("token") if isinstance(payload.get("token"), Mapping) else {}
            token_address = str(raw_token.get("address") or (row.get("token_out") if str(row.get("side")) == "buy" else row.get("token_in")) or "")
            if not token_address:
                continue
            token = TokenRef(
                int(row.get("chain_id") or os.getenv("FUND_CHAIN_ID", "4663")),
                token_address,
                str(raw_token.get("symbol") or token_address[:8]),
                float(raw_token["liquidityUsd"]) if raw_token.get("liquidityUsd") is not None else None,
                float(raw_token["priceUsd"]) if raw_token.get("priceUsd") is not None else None,
                float(raw_token["priceNative"]) if raw_token.get("priceNative") is not None else None,
            )
            intent = ExecutionIntent(
                str(row.get("idempotency_key")),
                str(row.get("side") or "buy"),
                int(row.get("chain_id") or token.chain_id),
                str(row.get("token_in")),
                str(row.get("token_out")),
                str(row.get("amount_in")),
                tuple(str(item) for item in (row.get("fly_ids") or [])),
                self.slippage_tolerance,
                int(time.time() * 1000),
                str(row.get("biological_event_id") or "") or None,
            )
            self.ledger.record_execution_attempt({
                "attempt_id": intent.idempotency_key,
                "idempotency_key": intent.idempotency_key,
                "status": "BROADCAST",
                "side": intent.side,
                "chain_id": intent.chain_id,
                "token_in": intent.token_in,
                "token_out": intent.token_out,
                "amount_in": intent.amount_in,
                "amount_out": result.get("expectedOutput"),
                "fly_ids_json": json.dumps(list(intent.fly_ids)),
                "execution_price": token.price_native,
                "gas": None,
                "slippage": intent.slippage_tolerance,
                "tx_hash": tx_hash,
                "nonce": None,
                "error": None,
                "created_ms": intent.created_at_ms,
                "updated_ms": int(time.time() * 1000),
            })
            self._persist_broadcast(intent, token, tx_hash, expected_output=str(result.get("expectedOutput") or "") or None, biological_event_id=intent.biological_event_id)
            known_ids.add(intent.idempotency_key)
            known_hashes.add(tx_hash.lower())

    def _reconcile_shared_execution_failures(self) -> None:
        """Release fly slots after failures that happened before broadcast.

        A failed queue row is not a fill and must not alter holdings.  For
        deterministic pre-broadcast failures, however, the corresponding
        fly slot must be released so a later biological BUY can enqueue a new
        attempt.  Rows that say a broadcast may already have succeeded are
        deliberately left unresolved because re-queuing them could double
        spend; those require transaction-hash reconciliation first.
        """

        if not isinstance(self.adapter, SupabaseExecutionAdapter):
            return
        failure_reader = getattr(self.adapter.queue, "execution_failures", None)
        if not callable(failure_reader):
            return
        try:
            rows = failure_reader(limit=100)
        except Exception:
            return
        for row in rows:
            execution_id = str(row.get("idempotency_key") or "")
            if not execution_id or execution_id in self.reconciled_failed_execution_ids:
                continue
            error = str(row.get("error") or "")
            result = row.get("result")
            tx_hash = result.get("txHash") if isinstance(result, Mapping) else None
            if _is_real_tx_hash(str(tx_hash or "")) or "broadcast succeeded" in error.lower():
                # Never automatically retry an ambiguous post-broadcast row.
                self.reconciled_failed_execution_ids.add(execution_id)
                continue
            side = str(row.get("side") or "").lower()
            for fly_id in (row.get("fly_ids") or []):
                position = self.positions.get(str(fly_id))
                if position is None:
                    continue
                if side == "buy" and position.state == FlyBehaviorState.QUALIFYING.value and position.held_amount <= 0:
                    self._save(replace(position, state=FlyBehaviorState.EXPLORING.value, departure_reason=None, updated_ms=int(time.time() * 1000)))
                    self.events.append({"type": "BUY_RETRY_READY", "status": "reconciled", "flyId": position.fly_id, "executionId": execution_id, "reason": error[:240]})
                elif side == "sell" and position.state == FlyBehaviorState.DEPARTING.value and position.held_amount > 0:
                    self.pending_departures.pop(position.fly_id, None)
                    self._save(replace(position, state=FlyBehaviorState.HOLDING.value, departure_reason=None, updated_ms=int(time.time() * 1000)))
                    self.events.append({"type": "SELL_RETRY_READY", "status": "reconciled", "flyId": position.fly_id, "executionId": execution_id, "reason": error[:240]})
            self.reconciled_failed_execution_ids.add(execution_id)

    def _flush_departures(self, timestamp: int, actions: list[AllocationIntent]) -> None:
        for fly_id, (due, target, reason, biological_event_id) in list(self.pending_rotations.items()):
            if timestamp < due:
                continue
            position = self.positions[fly_id]
            if position.state == FlyBehaviorState.HOLDING.value and position.held_amount > 0 and not self._position_matches_token(position, target):
                old = self.tokens_by_address.get(_token_key(position.chain_id or target.chain_id, position.token_address or "")) or TokenRef(position.chain_id or target.chain_id, position.token_address or "", position.token_symbol or "TOKEN")
                actions.append(AllocationIntent(fly_id, "sell", old, position.allocation_fraction, "rotation", timestamp, biological_event_id))
                actions.append(AllocationIntent(fly_id, "buy", target, position.allocation_fraction, reason, timestamp, biological_event_id))
                self._save(replace(position, state=FlyBehaviorState.QUALIFYING.value, updated_ms=timestamp))
            self.pending_rotations.pop(fly_id, None)
        for fly_id, (due, reason, token) in list(self.pending_departures.items()):
            if timestamp < due:
                continue
            position = self.positions[fly_id]
            if position.state == FlyBehaviorState.DEPARTING.value and position.held_amount > 0:
                actions.append(AllocationIntent(fly_id, "sell", token, position.allocation_fraction, reason, timestamp))
            self.pending_departures.pop(fly_id, None)

    def _minimum_hold_until(self, position: FlyCapitalPosition) -> int:
        if position.entry_timestamp_ms is None or position.held_amount <= 0:
            return 0
        return int(position.entry_timestamp_ms) + self.min_hold_ms

    @staticmethod
    def _position_matches_token(position: FlyCapitalPosition, token: TokenRef) -> bool:
        return (
            position.token_address is not None
            and position.token_address.lower() == token.address.lower()
            and int(position.chain_id or token.chain_id) == token.chain_id
        )

    def _persist_broadcast(self, intent: ExecutionIntent, token: TokenRef, tx_hash: str, *, expected_output: str | None = None, biological_event_id: str | None = None, wallet_before_native_wei: int | None = None) -> None:
        if not _is_real_tx_hash(tx_hash):
            return
        if wallet_before_native_wei is None and self.wallet is not None:
            try:
                wallet_before_native_wei = self.wallet.snapshot().native_balance_wei
            except Exception:
                wallet_before_native_wei = None
        now = int(time.time() * 1000)
        self.ledger.record_mainnet_execution({
            "execution_id": intent.idempotency_key,
            "biological_event_id": biological_event_id or intent.biological_event_id or intent.idempotency_key,
            "timestamp_ms": intent.created_at_ms,
            "fly_ids_json": json.dumps(list(intent.fly_ids)),
            "side": intent.side,
            "token_symbol": token.symbol,
            "token_address": token.address,
            "input_token": intent.token_in,
            "input_amount": intent.amount_in,
            "expected_output": expected_output,
            "tx_hash": tx_hash,
            "chain_id": intent.chain_id,
            "status": ReceiptStatus.BROADCAST,
            "explorer_url": explorer_url(tx_hash),
            "wallet_before_native_wei": str(wallet_before_native_wei) if wallet_before_native_wei is not None else None,
            "last_checked_ms": now,
        })
        self.ledger.record_execution_attempt({
            "attempt_id": intent.idempotency_key,
            "idempotency_key": intent.idempotency_key,
            "status": ReceiptStatus.BROADCAST,
            "side": intent.side,
            "chain_id": intent.chain_id,
            "token_in": intent.token_in,
            "token_out": intent.token_out,
            "amount_in": intent.amount_in,
            "amount_out": expected_output,
            "fly_ids_json": json.dumps(list(intent.fly_ids)),
            "execution_price": None,
            "gas": None,
            "slippage": intent.slippage_tolerance,
            "tx_hash": tx_hash,
            "nonce": None,
            "error": None,
            "created_ms": intent.created_at_ms,
            "updated_ms": now,
        })

    def _poll_mainnet_receipts(self, timestamp: int) -> None:
        if self.wallet is None or isinstance(self.adapter, SimulationExecutionAdapter):
            return
        now = time.monotonic()
        if now - self._last_receipt_poll < self.receipt_poll_seconds:
            return
        self._last_receipt_poll = now
        for row in self.ledger.rows("mainnet_executions", limit=100000):
            if row.get("status") not in {ReceiptStatus.BROADCAST, ReceiptStatus.PENDING}:
                continue
            tx_hash = str(row.get("tx_hash") or "")
            if not _is_real_tx_hash(tx_hash):
                continue
            try:
                observation = observe_receipt(
                    self.wallet,
                    tx_hash,
                    side=str(row.get("side") or "buy"),
                    token_address=str(row.get("token_address") or ""),
                    token_symbol=str(row.get("token_symbol") or "TOKEN"),
                    input_token=str(row.get("input_token") or ZERO_ADDRESS),
                    input_amount=str(row.get("input_amount") or "0"),
                    blockscout=self.blockscout,
                    wallet_before_native_wei=int(row["wallet_before_native_wei"]) if row.get("wallet_before_native_wei") else None,
                    output_decimals=self._token_decimals(str(row.get("token_address") or "")),
                )
            except Exception as exc:
                self.ledger.record_mainnet_execution({**row, "last_checked_ms": timestamp, "error": str(exc)})
                continue
            payload = {**row, "status": observation.status, "explorer_url": observation.explorer_url, "block_number": observation.block_number, "transaction_index": observation.transaction_index, "sender": observation.sender, "recipient": observation.recipient, "gas_used": observation.gas_used, "effective_gas_price": observation.effective_gas_price, "transaction_fee": observation.transaction_fee, "receipt_status": observation.receipt_status, "actual_input_amount": observation.actual_input_amount, "actual_output_amount": observation.actual_output_amount, "actual_token_received_json": json.dumps(observation.actual_token_received) if observation.actual_token_received is not None else None, "transfer_events_json": json.dumps(list(observation.transfer_events)), "blockscout_json": json.dumps(observation.blockscout) if observation.blockscout is not None else row.get("blockscout_json"), "error": observation.error, "last_checked_ms": timestamp}
            self.ledger.record_mainnet_execution(payload)
            self.ledger.update_trade_execution(row["execution_id"], observation)
            if observation.status == ReceiptStatus.CONFIRMED and row.get("status") != ReceiptStatus.CONFIRMED:
                self._apply_confirmed_execution(row, observation, timestamp)

    def _apply_confirmed_execution(self, row: Mapping[str, Any], observation: Any, timestamp: int) -> None:
        token_address = str(row.get("token_address") or "")
        chain_id = int(row.get("chain_id") or os.getenv("FUND_CHAIN_ID", "4663"))
        token = self.tokens_by_address.get(_token_key(chain_id, token_address)) or TokenRef(chain_id, token_address, str(row.get("token_symbol") or token_address[:8]))
        fly_ids = _json_list(row.get("fly_ids_json"))
        group = [(fly_id, token, "confirmed onchain", str(row.get("biological_event_id") or "") or None) for fly_id in fly_ids if fly_id in self.positions]
        if not group:
            return
        if str(row.get("side")) == "buy":
            if observation.actual_output_amount is None:
                return
            self._apply_fill("buy", group, float(observation.actual_output_amount), token, timestamp)
        else:
            self._apply_fill("sell", group, float(observation.actual_output_amount or 0.0), token, timestamp)

    def _token_decimals(self, token_address: str) -> int | None:
        if not token_address or token_address.lower() == ZERO_ADDRESS.lower() or self.wallet is None:
            return 18 if token_address and token_address.lower() == ZERO_ADDRESS.lower() else None
        try:
            return self.wallet.erc20_decimals(token_address)
        except Exception:
            return None

    def _execute_netted(self, actions: list[AllocationIntent], timestamp: int) -> None:
        grouped: dict[tuple[str, int, str], list[tuple[str, TokenRef, str, str | None]]] = {}
        for action in actions:
            side, fly_id, token, reason = action.side, action.fly_id, action.token, action.reason
            bucket = grouped.setdefault((side, token.chain_id, token.address.lower()), [])
            # A noisy stream can repeat a decision for one fly in the same
            # cycle. One fly owns one allocation; never double-count it in a
            # netted order.
            if any(item[0] == fly_id for item in bucket):
                continue
            bucket.append((fly_id, token, reason, action.biological_event_id))
        for (side, chain_id, token_address), group in grouped.items():
            fly_ids = tuple(item[0] for item in group)
            token = group[0][1]
            if side == "buy":
                amount = self._buy_amount_wei(len(group))
                token_in, token_out = ZERO_ADDRESS, token.address
            else:
                amount = sum(self.positions[fly_id].held_amount for fly_id in fly_ids)
                token_in, token_out = token.address, ZERO_ADDRESS
            if amount <= 0:
                self.pending_rebalance.append({"status": "blocked", "reason": "insufficient balance or allocation", "side": side, "flyIds": list(fly_ids), "tokenAddress": token.address})
                continue
            if side == "sell":
                amount = int(amount)
                if amount <= 0:
                    self.pending_rebalance.append({"status": "blocked", "reason": "sell amount below token base unit", "side": side, "flyIds": list(fly_ids), "tokenAddress": token.address})
                    continue
            reason = ",".join(sorted({item[2] for item in group}))
            biological_event_ids = tuple(item[3] for item in group if item[3])
            delta = PortfolioDelta(side, token, fly_ids, amount, token_in, token_out, reason, biological_event_ids)
            key = f"{delta.side}:{chain_id}:{token_address}:{','.join(fly_ids)}:{timestamp}"
            intent = ExecutionIntent(hashlib.sha256(key.encode()).hexdigest(), delta.side, chain_id, delta.token_in, delta.token_out, str(delta.amount_in), delta.fly_ids, self.slippage_tolerance, timestamp, ",".join(delta.biological_event_ids) or None)
            if intent.idempotency_key in self.processed_events:
                continue
            attempt = {"attempt_id": intent.idempotency_key, "idempotency_key": intent.idempotency_key, "status": "pending", "side": side, "chain_id": chain_id, "token_in": token_in, "token_out": token_out, "amount_in": str(amount), "amount_out": None, "fly_ids_json": json.dumps(list(fly_ids)), "execution_price": None, "gas": None, "slippage": self.slippage_tolerance, "tx_hash": None, "nonce": None, "error": None, "created_ms": timestamp, "updated_ms": timestamp}
            status = "blocked"
            amount_out = 0.0
            try:
                result = self.adapter.execute(intent, token)
                status = str(result.get("status", "prepared"))
                expected_output = _expected_output(result)
                amount_out = float(expected_output or 0)
                tx_hash = str(result.get("txHash") or "")
                if _is_real_tx_hash(tx_hash):
                    self._persist_broadcast(intent, token, tx_hash, expected_output=expected_output)
                    status = ReceiptStatus.BROADCAST
                attempt.update({"status": status, "amount_out": str(amount_out), "execution_price": result.get("executionPrice"), "gas": result.get("gas"), "tx_hash": result.get("txHash"), "nonce": result.get("nonce"), "updated_ms": int(time.time() * 1000)})
                if status in {"filled", "simulated"}:
                    self._apply_fill(side, group, amount_out, token, timestamp)
                else:
                    self.pending_rebalance.append({"status": status, "side": side, "flyIds": list(fly_ids), "tokenAddress": token.address, "amountIn": str(amount), "nonce": result.get("nonce"), "approval": result.get("approval"), "quote": result.get("quote"), "preparedTransaction": result.get("swap"), "executionIntent": intent.as_dict()})
                self.events.append({"type": side.upper(), "status": status, "flyIds": list(fly_ids), "tokenAddress": token.address, "amountIn": str(amount), "amountOut": str(amount_out), "executionPrice": result.get("executionPrice"), "gas": result.get("gas"), "estimatedGas": result.get("estimatedGas"), "slippage": result.get("slippage", self.slippage_tolerance), "nonce": result.get("nonce"), "txHash": result.get("txHash")})
            except Exception as exc:
                attempt.update({"status": "blocked", "error": str(exc), "updated_ms": int(time.time() * 1000)})
                self.pending_rebalance.append({"status": "blocked", "reason": str(exc), "side": side, "flyIds": list(fly_ids), "tokenAddress": token.address})
            self.ledger.record_trade({"trade_id": intent.idempotency_key, "timestamp_ms": timestamp, "chain_id": chain_id, "dex_id": "uniswap", "token_in": token_in, "token_out": token_out, "amount_in": str(amount), "amount_out": str(amount_out), "usd_value": (token.price_usd or 0.0) * amount_out, "tx_hash": attempt.get("tx_hash"), "status": status, "neuroswarm_decision_id": ",".join(fly_ids), "fees_usd": None, "gas_usd": None})
            self.ledger.record_execution_attempt(attempt)
            self.processed_events.add(intent.idempotency_key)

    def _apply_fill(self, side: str, group: list[tuple[str, TokenRef, str, str | None]], amount_out: float, token: TokenRef, timestamp: int) -> None:
        if side == "buy":
            per_fly = amount_out / max(1, len(group))
            for fly_id, _, _, _ in group:
                position = self.positions[fly_id]
                self._save(replace(position, state=FlyBehaviorState.HOLDING.value, chain_id=token.chain_id, token_address=token.address, token_symbol=token.symbol, entry_timestamp_ms=timestamp, entry_price_usd=token.price_usd, held_amount=per_fly, current_value_usd=(token.price_usd or 0.0) * per_fly, unrealized_pnl_usd=0.0, departure_reason=None, updated_ms=timestamp))
        else:
            for fly_id, _, reason, _ in group:
                position = self.positions[fly_id]
                current = (token.price_usd or position.entry_price_usd or 0.0) * position.held_amount
                basis = (position.entry_price_usd or 0.0) * position.held_amount
                self._save(replace(position, state=FlyBehaviorState.EXPLORING.value, token_address=None, token_symbol=None, held_amount=0.0, current_value_usd=0.0, realized_pnl_usd=position.realized_pnl_usd + current - basis, unrealized_pnl_usd=0.0, departure_reason=reason, updated_ms=timestamp))

    def _buy_amount_wei(self, count: int) -> int:
        if self.wallet is None:
            return 10**15 * count
        try:
            return int(self.wallet.snapshot().available_native_wei * self.per_fly_allocation_fraction) * count
        except Exception:
            return 0

    def _save(self, position: FlyCapitalPosition) -> None:
        self.positions[position.fly_id] = position
        self.ledger.upsert_fly_position(position.ledger_dict())

    def _event(self, behavior: BehaviorTradeIntent, event_type: str, reason: str) -> None:
        self.events.append({"type": event_type, "status": "observed", "flyId": behavior.fly_id, "habitatId": behavior.habitat_id, "side": behavior.side, "reason": reason, "observedAtMs": behavior.observed_at_ms, "confidence": behavior.confidence})


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_real_tx_hash(value: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{64}", str(value or "")))


def _expected_output(result: Mapping[str, Any]) -> str | None:
    direct = result.get("amountOut")
    if direct is not None:
        return str(direct)
    quote = result.get("quote")
    if not isinstance(quote, Mapping):
        return None
    output = quote.get("output")
    if isinstance(output, Mapping) and output.get("amount") is not None:
        return str(output["amount"])
    order_info = quote.get("orderInfo")
    outputs = order_info.get("outputs") if isinstance(order_info, Mapping) else None
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], Mapping):
        if outputs[0].get("startAmount") is not None:
            return str(outputs[0]["startAmount"])
    return None


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _execution_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    actual_received = row.get("actual_token_received_json")
    transfers = row.get("transfer_events_json")
    try:
        actual_received = json.loads(actual_received) if actual_received else None
    except (TypeError, json.JSONDecodeError):
        actual_received = None
    try:
        transfers = json.loads(transfers) if transfers else []
    except (TypeError, json.JSONDecodeError):
        transfers = []
    return {
        "executionId": row.get("execution_id"),
        "biologicalEventId": row.get("biological_event_id"),
        "timestamp": row.get("timestamp_ms"),
        "flyIds": _json_list(row.get("fly_ids_json")),
        "side": row.get("side"),
        "tokenSymbol": row.get("token_symbol"),
        "tokenAddress": row.get("token_address"),
        "inputToken": row.get("input_token"),
        "inputAmount": row.get("input_amount"),
        "expectedOutput": row.get("expected_output"),
        "txHash": row.get("tx_hash"),
        "chainId": row.get("chain_id"),
        "status": row.get("status"),
        "explorerUrl": row.get("explorer_url"),
        "blockNumber": row.get("block_number"),
        "transactionIndex": row.get("transaction_index"),
        "from": row.get("sender"),
        "to": row.get("recipient"),
        "gasUsed": row.get("gas_used"),
        "effectiveGasPrice": row.get("effective_gas_price"),
        "transactionFee": row.get("transaction_fee"),
        "receiptStatus": row.get("receipt_status"),
        "actualInputAmount": row.get("actual_input_amount"),
        "actualOutputAmount": row.get("actual_output_amount"),
        "actualTokenReceived": actual_received,
        "transferEvents": transfers,
        "blockscout": _json_object(row.get("blockscout_json")),
        "error": row.get("error"),
    }


def _json_object(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _token_key(chain_id: int, address: str) -> str:
    """Resolve assets by network and contract, never by symbol alone."""
    return f"{int(chain_id)}:{address.lower()}"
