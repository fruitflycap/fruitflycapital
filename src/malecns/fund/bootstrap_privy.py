"""Inspect or explicitly create the configured Privy EVM treasury."""
from __future__ import annotations
import argparse, json
from .privy_client import PrivyClient, PrivyConfig

def main() -> None:
    parser = argparse.ArgumentParser(description="Fruit Fly Capital Privy treasury bootstrap")
    parser.add_argument("--create", action="store_true", help="explicitly create one Ethereum wallet if no wallet ID is configured")
    parser.add_argument("--balance", action="store_true", help="read the configured wallet balance")
    args = parser.parse_args(); config = PrivyConfig.from_env()
    report = {"configured": config.configured, "walletId": config.wallet_id, "walletAddress": config.wallet_address, "policyId": config.policy_id, "secretsLoaded": bool(config.app_secret)}
    if config.configured:
        client = PrivyClient(config)
        if args.create and not config.wallet_id: report["createdWallet"] = client.create_wallet()
        elif config.wallet_id: report["wallet"] = client.get_wallet()
        if args.balance and (config.wallet_id or report.get("createdWallet")): report["balance"] = client.get_balance(config.wallet_id or report["createdWallet"]["id"])
    print(json.dumps(report, indent=2, default=str))

if __name__ == "__main__": main()

