"""Small append-only accounting journal backed by sqlite3.

The ledger is a book of observed events, not an authority over on-chain state.
Every event carries a source and external identity so reconciliation can report
disagreements rather than silently rewriting history.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, source TEXT NOT NULL, external_id TEXT, payload_json TEXT NOT NULL, UNIQUE(source, external_id));
CREATE TABLE IF NOT EXISTS deposits (deposit_id TEXT PRIMARY KEY, timestamp_ms INTEGER NOT NULL, chain_id INTEGER, asset TEXT NOT NULL, amount REAL NOT NULL, shares REAL NOT NULL, tx_hash TEXT, source_event_id TEXT);
CREATE TABLE IF NOT EXISTS withdrawals (withdrawal_id TEXT PRIMARY KEY, timestamp_ms INTEGER NOT NULL, chain_id INTEGER, asset TEXT NOT NULL, amount REAL NOT NULL, shares REAL NOT NULL, status TEXT NOT NULL, tx_hash TEXT, source_event_id TEXT);
CREATE TABLE IF NOT EXISTS trades (trade_id TEXT PRIMARY KEY, timestamp_ms INTEGER NOT NULL, chain_id INTEGER NOT NULL, dex_id TEXT NOT NULL, token_in TEXT NOT NULL, token_out TEXT NOT NULL, amount_in TEXT NOT NULL, amount_out TEXT, usd_value REAL, tx_hash TEXT, status TEXT NOT NULL, round_id TEXT, neuroswarm_decision_id TEXT, gas_usd REAL, fees_usd REAL, realized_pnl_usd REAL);
CREATE TABLE IF NOT EXISTS positions (chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, symbol TEXT, asset_class TEXT NOT NULL DEFAULT 'crypto', amount REAL NOT NULL, cost_basis_usd REAL NOT NULL DEFAULT 0, updated_ms INTEGER NOT NULL, PRIMARY KEY(chain_id, token_address));
CREATE TABLE IF NOT EXISTS nav_snapshots (snapshot_id TEXT PRIMARY KEY, timestamp_ms INTEGER NOT NULL, nav_usd REAL NOT NULL, nav_per_share_usd REAL, shares_outstanding REAL, source TEXT NOT NULL, provenance_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chain_balances (chain_id INTEGER NOT NULL, wallet_address TEXT NOT NULL, token_address TEXT NOT NULL, symbol TEXT, asset_class TEXT NOT NULL DEFAULT 'crypto', amount REAL NOT NULL, observed_ms INTEGER NOT NULL, source TEXT NOT NULL, PRIMARY KEY(chain_id, wallet_address, token_address));
CREATE TABLE IF NOT EXISTS asset_metadata (chain_id INTEGER NOT NULL, token_address TEXT NOT NULL, symbol TEXT, name TEXT, asset_class TEXT NOT NULL DEFAULT 'crypto', decimals INTEGER, source TEXT NOT NULL, PRIMARY KEY(chain_id, token_address));
CREATE TABLE IF NOT EXISTS fly_positions (fly_id TEXT PRIMARY KEY, state TEXT NOT NULL, chain_id INTEGER, token_address TEXT, token_symbol TEXT, allocation_fraction REAL NOT NULL, entry_timestamp_ms INTEGER, entry_price_usd REAL, current_value_usd REAL NOT NULL DEFAULT 0, realized_pnl_usd REAL NOT NULL DEFAULT 0, unrealized_pnl_usd REAL NOT NULL DEFAULT 0, departure_reason TEXT, held_amount REAL NOT NULL DEFAULT 0, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS execution_attempts (attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, side TEXT NOT NULL, chain_id INTEGER NOT NULL, token_in TEXT NOT NULL, token_out TEXT NOT NULL, amount_in TEXT NOT NULL, amount_out TEXT, fly_ids_json TEXT NOT NULL, execution_price TEXT, gas TEXT, slippage REAL, tx_hash TEXT, nonce TEXT, error TEXT, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mainnet_executions (execution_id TEXT PRIMARY KEY, biological_event_id TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, fly_ids_json TEXT NOT NULL, side TEXT NOT NULL, token_symbol TEXT NOT NULL, token_address TEXT NOT NULL, input_token TEXT NOT NULL, input_amount TEXT NOT NULL, expected_output TEXT, tx_hash TEXT NOT NULL UNIQUE, chain_id INTEGER NOT NULL, status TEXT NOT NULL, explorer_url TEXT NOT NULL, block_number INTEGER, transaction_index INTEGER, sender TEXT, recipient TEXT, gas_used TEXT, effective_gas_price TEXT, transaction_fee TEXT, receipt_status TEXT, actual_input_amount TEXT, actual_output_amount TEXT, actual_token_received_json TEXT, transfer_events_json TEXT, blockscout_json TEXT, wallet_before_native_wei TEXT, error TEXT, last_checked_ms INTEGER NOT NULL);
"""


class FundLedger:
    def __init__(self, path: str | Path = "data/fund/fund.db") -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        existing_trade_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(trades)")}
        if "realized_pnl_usd" not in existing_trade_columns:
            self.connection.execute("ALTER TABLE trades ADD COLUMN realized_pnl_usd REAL")
        existing_fly_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(fly_positions)")}
        if "held_amount" not in existing_fly_columns:
            self.connection.execute("ALTER TABLE fly_positions ADD COLUMN held_amount REAL NOT NULL DEFAULT 0")
        existing_attempt_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(execution_attempts)")}
        if "nonce" not in existing_attempt_columns:
            self.connection.execute("ALTER TABLE execution_attempts ADD COLUMN nonce TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def append_event(self, event_type: str, payload: Mapping[str, Any], *, source: str, external_id: str | None = None, timestamp_ms: int | None = None) -> str | None:
        event_id = str(uuid.uuid4())
        try:
            self.connection.execute("INSERT INTO fund_events VALUES (?, ?, ?, ?, ?, ?)", (event_id, event_type, timestamp_ms or int(time.time() * 1000), source, external_id, json.dumps(dict(payload), sort_keys=True)))
        except sqlite3.IntegrityError:
            self.connection.rollback()
            return None
        self.connection.commit()
        return event_id

    def record_deposit(self, *, asset: str, amount: float, shares: float, chain_id: int | None = None, tx_hash: str | None = None, timestamp_ms: int | None = None, source_event_id: str | None = None, deposit_id: str | None = None) -> str:
        identifier = deposit_id or str(uuid.uuid4())
        self.connection.execute("INSERT INTO deposits VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (identifier, timestamp_ms or int(time.time() * 1000), chain_id, asset, amount, shares, tx_hash, source_event_id))
        self.connection.commit()
        return identifier

    def record_withdrawal(self, *, asset: str, amount: float, shares: float, status: str, chain_id: int | None = None, tx_hash: str | None = None, timestamp_ms: int | None = None, source_event_id: str | None = None, withdrawal_id: str | None = None) -> str:
        identifier = withdrawal_id or str(uuid.uuid4())
        self.connection.execute("INSERT INTO withdrawals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (identifier, timestamp_ms or int(time.time() * 1000), chain_id, asset, amount, shares, status, tx_hash, source_event_id))
        self.connection.commit()
        return identifier

    def record_trade(self, trade: Mapping[str, Any]) -> str:
        identifier = str(trade.get("trade_id") or uuid.uuid4())
        fields = (identifier, int(trade.get("timestamp_ms") or time.time() * 1000), int(trade["chain_id"]), str(trade.get("dex_id", "unknown")), str(trade["token_in"]), str(trade["token_out"]), str(trade["amount_in"]), trade.get("amount_out"), trade.get("usd_value"), trade.get("tx_hash"), str(trade.get("status", "proposed")), trade.get("round_id"), trade.get("neuroswarm_decision_id"), trade.get("gas_usd"), trade.get("fees_usd"), trade.get("realized_pnl_usd"))
        self.connection.execute("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", fields)
        self.connection.commit()
        return identifier

    def upsert_position(self, *, chain_id: int, token_address: str, amount: float, cost_basis_usd: float, symbol: str | None = None, asset_class: str = "crypto", updated_ms: int | None = None) -> None:
        self.connection.execute("""INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(chain_id, token_address) DO UPDATE SET symbol=excluded.symbol, asset_class=excluded.asset_class, amount=excluded.amount, cost_basis_usd=excluded.cost_basis_usd, updated_ms=excluded.updated_ms""", (chain_id, token_address, symbol, asset_class, amount, cost_basis_usd, updated_ms or int(time.time() * 1000)))
        self.connection.commit()

    def record_nav(self, nav_usd: float, nav_per_share_usd: float | None, shares_outstanding: float | None, *, source: str, provenance: Mapping[str, Any] | None = None, timestamp_ms: int | None = None) -> str:
        identifier = str(uuid.uuid4())
        self.connection.execute("INSERT INTO nav_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)", (identifier, timestamp_ms or int(time.time() * 1000), nav_usd, nav_per_share_usd, shares_outstanding, source, json.dumps(dict(provenance or {}), sort_keys=True)))
        self.connection.commit()
        return identifier

    def record_chain_balance(self, *, chain_id: int, wallet_address: str, token_address: str, amount: float, source: str, symbol: str | None = None, asset_class: str = "crypto", observed_ms: int | None = None) -> None:
        self.connection.execute("""INSERT INTO chain_balances VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(chain_id, wallet_address, token_address) DO UPDATE SET symbol=excluded.symbol, asset_class=excluded.asset_class, amount=excluded.amount, observed_ms=excluded.observed_ms, source=excluded.source""", (chain_id, wallet_address, token_address, symbol, asset_class, amount, observed_ms or int(time.time() * 1000), source))
        self.connection.commit()

    def rows(self, table: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if table not in {"fund_events", "deposits", "withdrawals", "trades", "positions", "nav_snapshots", "chain_balances", "asset_metadata", "fly_positions", "execution_attempts", "mainnet_executions"}:
            raise ValueError("unknown ledger table")
        return [dict(row) for row in self.connection.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,))]

    def upsert_fly_position(self, position: Mapping[str, Any]) -> None:
        self.connection.execute(
            """INSERT INTO fly_positions (fly_id, state, chain_id, token_address, token_symbol, allocation_fraction, entry_timestamp_ms, entry_price_usd, current_value_usd, realized_pnl_usd, unrealized_pnl_usd, departure_reason, held_amount, updated_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fly_id) DO UPDATE SET state=excluded.state, chain_id=excluded.chain_id,
            token_address=excluded.token_address, token_symbol=excluded.token_symbol,
            allocation_fraction=excluded.allocation_fraction, entry_timestamp_ms=excluded.entry_timestamp_ms,
            entry_price_usd=excluded.entry_price_usd, current_value_usd=excluded.current_value_usd,
            realized_pnl_usd=excluded.realized_pnl_usd, unrealized_pnl_usd=excluded.unrealized_pnl_usd,
            departure_reason=excluded.departure_reason, held_amount=excluded.held_amount, updated_ms=excluded.updated_ms""",
            tuple(position.get(key) for key in ("fly_id", "state", "chain_id", "token_address", "token_symbol", "allocation_fraction", "entry_timestamp_ms", "entry_price_usd", "current_value_usd", "realized_pnl_usd", "unrealized_pnl_usd", "departure_reason", "held_amount", "updated_ms")),
        )
        self.connection.commit()

    def record_execution_attempt(self, attempt: Mapping[str, Any]) -> None:
        self.connection.execute(
            """INSERT INTO execution_attempts (attempt_id, idempotency_key, status, side, chain_id, token_in, token_out, amount_in, amount_out, fly_ids_json, execution_price, gas, slippage, tx_hash, nonce, error, created_ms, updated_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET status=excluded.status, amount_out=excluded.amount_out,
            execution_price=excluded.execution_price, gas=excluded.gas, slippage=excluded.slippage,
            tx_hash=excluded.tx_hash, nonce=excluded.nonce, error=excluded.error, updated_ms=excluded.updated_ms""",
            tuple(attempt.get(key) for key in ("attempt_id", "idempotency_key", "status", "side", "chain_id", "token_in", "token_out", "amount_in", "amount_out", "fly_ids_json", "execution_price", "gas", "slippage", "tx_hash", "nonce", "error", "created_ms", "updated_ms")),
        )
        self.connection.commit()

    def record_mainnet_execution(self, execution: Mapping[str, Any]) -> None:
        """Persist a real-hash execution and every later receipt transition."""
        fields = (
            "execution_id", "biological_event_id", "timestamp_ms", "fly_ids_json", "side", "token_symbol",
            "token_address", "input_token", "input_amount", "expected_output", "tx_hash", "chain_id", "status",
            "explorer_url", "block_number", "transaction_index", "sender", "recipient", "gas_used",
            "effective_gas_price", "transaction_fee", "receipt_status", "actual_input_amount", "actual_output_amount",
            "actual_token_received_json", "transfer_events_json", "blockscout_json", "wallet_before_native_wei",
            "error", "last_checked_ms",
        )
        values = tuple(execution.get(key) for key in fields)
        self.connection.execute(
            """INSERT INTO mainnet_executions (execution_id, biological_event_id, timestamp_ms, fly_ids_json, side, token_symbol, token_address, input_token, input_amount, expected_output, tx_hash, chain_id, status, explorer_url, block_number, transaction_index, sender, recipient, gas_used, effective_gas_price, transaction_fee, receipt_status, actual_input_amount, actual_output_amount, actual_token_received_json, transfer_events_json, blockscout_json, wallet_before_native_wei, error, last_checked_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(execution_id) DO UPDATE SET status=excluded.status, explorer_url=excluded.explorer_url,
            block_number=excluded.block_number, transaction_index=excluded.transaction_index, sender=excluded.sender,
            recipient=excluded.recipient, gas_used=excluded.gas_used, effective_gas_price=excluded.effective_gas_price,
            transaction_fee=excluded.transaction_fee, receipt_status=excluded.receipt_status,
            actual_input_amount=excluded.actual_input_amount, actual_output_amount=excluded.actual_output_amount,
            actual_token_received_json=excluded.actual_token_received_json, transfer_events_json=excluded.transfer_events_json,
            blockscout_json=excluded.blockscout_json, error=excluded.error, last_checked_ms=excluded.last_checked_ms""",
            values,
        )
        self.connection.commit()

    def update_trade_execution(self, trade_id: str, observation: Any) -> None:
        """Keep the legacy trade index aligned with canonical receipt state."""
        self.connection.execute(
            "UPDATE trades SET status=?, amount_out=?, gas_usd=? WHERE trade_id=?",
            (str(getattr(observation, "status", "PENDING")), getattr(observation, "actual_output_amount", None), None, trade_id),
        )
        self.connection.commit()
