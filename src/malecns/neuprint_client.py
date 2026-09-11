"""Thin, explicit client for the official MaleCNS neuPrint dataset."""

from __future__ import annotations

import os
import json
from typing import Any

from .loader import normalize_edges


class NeuprintDependencyError(ImportError):
    pass


class MaleCNSClient:
    """Access ``male-cns:v1.0`` without creating cross-fly neural edges."""

    def __init__(self, token: str | None = None, server: str | None = None, dataset: str | None = None, client: Any | None = None):
        self.server = server or os.getenv("NEUPRINT_SERVER", "https://neuprint.janelia.org")
        self.dataset = dataset or os.getenv("NEUPRINT_DATASET", "male-cns:v1.0")
        if self.dataset != "male-cns:v1.0":
            raise ValueError(f"This bootstrap is restricted to MaleCNS v1.0, got {self.dataset!r}")
        if client is not None:
            self.client = client
            return
        try:
            from neuprint import Client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise NeuprintDependencyError("Install neuprint-python for live neuPrint access") from exc
        self.client = Client(self.server, dataset=self.dataset, token=token or os.getenv("NEUPRINT_TOKEN"))

    def query_neurons(
        self, *, body_id: Any = None, type: Any = None, class_name: Any = None, class_: Any = None, side: Any = None
    ) -> Any:
        """Query official node annotations using server-side predicates."""
        if class_name is not None and class_ is not None:
            raise ValueError("Pass only one of class_name or class_")
        values = {
            "body_ids": _as_list(body_id),
            "types": _as_list(type),
            "classes": _as_list(class_name if class_name is not None else class_),
            "sides": _as_list(side),
        }
        clauses = []
        if values["body_ids"] is not None:
            clauses.append(f"n.bodyId IN {_cypher_list(values['body_ids'])}")
        if values["types"] is not None:
            clauses.append(f"n.type IN {_cypher_list(values['types'])}")
        if values["classes"] is not None:
            clauses.append(f"n.`class` IN {_cypher_list(values['classes'])}")
        if values["sides"] is not None:
            side_list = _cypher_list(values["sides"])
            clauses.append(
                f"(n.somaSide IN {side_list} OR "
                f"(n.somaSide IS NULL AND n.rootSide IN {side_list}))"
            )
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cypher = (
            "MATCH (n:Neuron)" + where + " "
            "RETURN n.bodyId AS body_id, n.type AS type, n.class AS class, "
            "n.subclass AS subclass, n.superclass AS superclass, "
            "CASE WHEN n.somaSide IS NULL THEN n.rootSide ELSE n.somaSide END AS side, "
            "n.nerve AS nerve, "
            "n.hemilineage AS hemilineage, n.status AS status, n.pre AS pre_count, "
            "n.post AS post_count"
        )
        # neuprint-python's Client.fetch_custom accepts Cypher and format, but
        # does not expose query parameters. Values are encoded as JSON/Cypher
        # literals above, which avoids string concatenation without an escape.
        return self.client.fetch_custom(cypher, format="pandas")

    def connectivity(self, *, body_ids: Any = None, direction: str = "outgoing") -> Any:
        """Fetch weighted incoming or outgoing connectivity from neuPrint."""
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("direction must be 'incoming' or 'outgoing'")
        try:
            from neuprint import fetch_adjacencies
        except ImportError as exc:  # pragma: no cover
            raise NeuprintDependencyError("Install neuprint-python for live neuPrint access") from exc
        ids = _as_list(body_ids)
        if direction == "outgoing":
            result = fetch_adjacencies(
                sources=ids, targets=None, omit_rois=True, weight_props=["weight"], client=self.client
            )
        else:
            result = fetch_adjacencies(
                sources=None, targets=ids, omit_rois=True, weight_props=["weight"], client=self.client
            )
        # neuprint-python returns (neuron_info, connection_edges).
        edge_frame = result[1] if isinstance(result, tuple) else result
        return normalize_edges(edge_frame)


def _as_list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _cypher_list(values: list[Any]) -> str:
    """Encode scalar query values as a safe Cypher list literal."""
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"
