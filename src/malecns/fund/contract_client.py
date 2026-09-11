"""Read-only/event-indexing boundary for FruitFlyFundVault.

Web3 is optional. Importing this module never requires RPC credentials or
opens a network connection.
"""
from __future__ import annotations
from typing import Any, Mapping

class FruitFlyFundContractClient:
    def __init__(self, rpc_url: str, contract_address: str, abi: list[Mapping[str, Any]] | None = None) -> None:
        self.rpc_url, self.contract_address, self.abi = rpc_url, contract_address, abi or []
        try:
            from web3 import Web3
        except ImportError as error: raise RuntimeError("install the optional 'fund' dependency to use Web3 contract reads") from error
        self.web3 = Web3(Web3.HTTPProvider(rpc_url)); self.contract = self.web3.eth.contract(address=contract_address, abi=self.abi)
    def latest_block(self) -> int: return int(self.web3.eth.block_number)
    def events(self, event_name: str, *, from_block: int, to_block: int | str = "latest") -> list[dict[str, Any]]:
        event = getattr(self.contract.events, event_name)(); return [dict(item["args"]) | {"blockNumber": item["blockNumber"], "logIndex": item["logIndex"]} for item in event.get_logs(from_block=from_block, to_block=to_block)]

