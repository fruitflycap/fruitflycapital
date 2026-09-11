"""Chain balance interface; concrete RPC reads are deliberately injectable."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence

@dataclass(frozen=True)
class ChainBalance:
    chain_id: int
    wallet_address: str
    token_address: str
    amount: float
    symbol: str | None = None
    asset_class: str = "crypto"
    source: str = "unknown"

class ChainClient(Protocol):
    def get_balances(self, chain_id: int, wallet_address: str, token_addresses: Sequence[str]) -> Sequence[ChainBalance]: ...

class FakeChainClient:
    def __init__(self, balances: Sequence[ChainBalance] = ()) -> None: self.balances = list(balances)
    def get_balances(self, chain_id: int, wallet_address: str, token_addresses: Sequence[str]) -> Sequence[ChainBalance]:
        wanted = set(token_addresses)
        return [item for item in self.balances if item.chain_id == chain_id and item.wallet_address.lower() == wallet_address.lower() and item.token_address in wanted]

