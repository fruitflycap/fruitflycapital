"""Server-only Supabase REST queue for cross-service execution intents."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class SupabaseQueueError(RuntimeError):
    pass


class SupabaseIntentQueue:
    def __init__(self, url: str, key: str, table: str = "execution_intents") -> None:
        self.url = url.rstrip("/")
        self.key = key
        self.table = table

    @classmethod
    def from_env(cls) -> "SupabaseIntentQueue | None":
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            return None
        return cls(url, key, os.getenv("SUPABASE_INTENT_TABLE", "execution_intents").strip() or "execution_intents")

    def _request(self, method: str, path: str, body: Any = None, query: str = "", prefer: str | None = None) -> Any:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        request = Request(f"{self.url}/rest/v1/{path}{query}", headers=headers, data=json.dumps(body).encode() if body is not None else None, method=method)
        try:
            with urlopen(request, timeout=float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "8"))) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SupabaseQueueError(f"Supabase queue HTTP {exc.code}: {detail[:500]}") from exc
        except Exception as exc:
            raise SupabaseQueueError(f"Supabase queue request failed: {exc}") from exc

    def enqueue(self, payload: Mapping[str, Any]) -> bool:
        intent = payload.get("executionIntent")
        token = payload.get("token")
        if not isinstance(intent, Mapping) or not isinstance(token, Mapping):
            raise SupabaseQueueError("queue payload must contain executionIntent and token")
        row = {
            "idempotency_key": intent["idempotencyKey"],
            "side": intent["side"],
            "chain_id": int(intent["chainId"]),
            "token_in": intent["tokenIn"],
            "token_out": intent["tokenOut"],
            "amount_in": str(intent["amountIn"]),
            "fly_ids": list(intent.get("flyIds") or []),
            "biological_event_id": intent.get("biologicalEventId"),
            "payload": dict(payload),
        }
        self._request("POST", self.table, [row], prefer="resolution=ignore-duplicates,return=minimal")
        return True

    def record_behavior_proposal(self, behavior: Mapping[str, Any], token: Mapping[str, Any] | None) -> bool:
        """Persist a biological proposal before execution eligibility is known.

        The worker claims only ``pending`` rows. These ``observed`` rows make
        the biological audit durable across browser users and reconnects while
        keeping incomplete proposals (for example a sell without a held
        balance yet) out of the executable queue.
        """

        intent_id = str(behavior.get("intentId") or "").strip()
        side = str(behavior.get("side") or "").lower()
        if not intent_id or side not in {"buy", "sell"}:
            raise SupabaseQueueError("behavior proposal requires intentId and BUY/SELL side")
        token_data = dict(token or {})
        token_address = str(token_data.get("address") or "0x0000000000000000000000000000000000000000")
        chain_id = int(token_data.get("chainId") or os.getenv("FUND_CHAIN_ID", "4663"))
        zero = "0x0000000000000000000000000000000000000000"
        row = {
            "idempotency_key": f"proposal:{intent_id}",
            "side": side,
            "chain_id": chain_id,
            "token_in": zero if side == "buy" else token_address,
            "token_out": token_address if side == "buy" else zero,
            "amount_in": "0",
            "fly_ids": [str(behavior.get("flyId") or "")],
            "biological_event_id": intent_id,
            "behavior_intent_id": intent_id,
            "execution_eligible": False,
            "proposal_reason": "biological proposal recorded before executable allocation",
            "status": "observed",
            "payload": {
                "behaviorIntent": dict(behavior),
                "token": token_data,
                "proposalStatus": "observed",
            },
        }
        self._request("POST", self.table, [row], prefer="resolution=ignore-duplicates,return=minimal")
        return True

    def claim(self, worker_id: str, limit: int = 1) -> list[dict[str, Any]]:
        rows = self._request("POST", "rpc/claim_execution_intents", {"p_worker_id": worker_id, "p_limit": limit, "p_lease_seconds": int(os.getenv("FUND_QUEUE_LEASE_SECONDS", "120"))})
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    def finish(self, key: str, status: str, result: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        query = f"?idempotency_key=eq.{key}"
        body = {"status": status, "result": dict(result) if result is not None else None, "error": error, "lease_until": None, "updated_at": "now()"}
        # PostgREST cannot evaluate now() in a JSON PATCH, so omit it; the
        # database timestamp remains accurate enough for queue recovery.
        body.pop("updated_at")
        self._request("PATCH", self.table, body, query=query, prefer="return=minimal")

    def execution_results(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return shared queue rows that contain a real executor result.

        The browser-facing brain service and the separately-run executor do
        not share a filesystem. The queue result is therefore the durable
        handoff for a real transaction hash and receipt status.
        """

        rows = self._request(
            "GET",
            self.table,
            query=f"?select=idempotency_key,side,chain_id,token_in,token_out,amount_in,fly_ids,biological_event_id,payload,status,result,created_at,updated_at&status=in.(broadcast,confirmed)&order=updated_at.desc&limit={max(1, min(int(limit), 500))}",
        )
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    def execution_failures(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return failed executable rows for brain-state reconciliation.

        ``observed`` proposal rows are intentionally excluded.  The brain
        needs the failed amount-bearing rows so a fly that was left in
        ``QUALIFYING`` after a quote/gas failure can become eligible for a new
        visit instead of being suppressed forever.
        """

        rows = self._request(
            "GET",
            self.table,
            query=f"?select=idempotency_key,side,fly_ids,biological_event_id,status,error,result,created_at,updated_at&status=eq.failed&order=updated_at.desc&limit={max(1, min(int(limit), 500))}",
        )
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    @staticmethod
    def new_worker_id() -> str:
        return f"render-worker-{uuid.uuid4().hex[:12]}"
