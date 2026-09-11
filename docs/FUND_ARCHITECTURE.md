# Fruit Fly Capital fund / treasury boundary

This is a local, Robinhood Chain wallet architecture with guarded execution. It is not a regulated
public fund and does not claim trustless production NAV accounting.

```text
market → habitat → MaleCNS → swarm observation → allocation → TradeIntent
                                             ↓
                              RiskGuard → Uniswap API → direct wallet
                                             ↓
                                      portfolio ledger
```

The saved `FruitFlyFundVault.sol` contract and its Foundry scripts remain in
the repository for later use, but are inactive in wallet mode. The configured
wallet owns the funds directly, and trades keep `FUND_GAS_RESERVE_WEI`
(default `0.002 ETH`) untouched.

The autonomous runtime gives every primary brain exactly `1 / 16 = 6.25%`
of deployable capital. It persists each fly's state and position, debounces
departure events, aggregates same-token orders, and records every execution
attempt. Simulation mode fills automatically for end-to-end demos. The
mainnet adapter performs identity, allowance, quote, slippage, liquidity, gas,
nonce, and calldata checks, then hands the transaction to the configured
external authorization boundary.

## Contract

`contracts/src/FruitFlyFundVault.sol` is an explicit share-accounting vault:
the accounting asset is a real ERC-20 selected at deployment and FFC shares
have 18 decimals. The Robinhood Chain testnet deployment uses the verified
testnet WETH contract at `0x0dd1df4fdd55808c9d530c9599bea5107f6b9b4e`, whose
18 decimals are read by the vault at construction. The
first deposit establishes one accounting-asset unit per share. Later deposits
use the current integer NAV/share. NAV is liquid WETH plus
`reportedStrategyNavAsset`.

The strategy treasury is one configured address; capital cannot be deployed to
an arbitrary recipient. Withdrawals use `REQUESTED → FUNDED → CLAIMED` and
escrow shares at request time. The request stores the NAV snapshot and fixed
WETH amount used for the eventual claim.

### Native ETH deposits

The Robinhood testnet fund proxy accepts native ETH. A normal ETH transfer to
the **proxy** is treated as a deposit for the sender: the vault wraps the ETH
into its configured WETH asset and mints FFC shares to that sender. The
explicit equivalent is:

```text
proxy.depositETH(YOUR_ADDRESS, value = 0.01 ETH)
```

The standard ERC-20 path remains available:

```text
WETH.approve(FUND_PROXY, amount)
FUND_PROXY.deposit(amount, YOUR_ADDRESS)
```

Do not send ETH to the WETH token and expect fund shares. That only wraps ETH
into WETH in the sender's WETH balance. Do not send WETH directly to the proxy
either: an ERC-20 transfer does not identify a share receiver, so the vault
cannot credit shares for an unsolicited transfer. Use `deposit` after approval.

Plain native transfers made through a normal transaction are supported; forced
ETH transfers (for example via `selfdestruct`) cannot be associated with a
receiver and are not deposits.

V1 uses an authorized offchain NAV reporter and is not a trustless production
fund accounting system. OpenZeppelin AccessControl, SafeERC20,
ReentrancyGuard, Pausable, ERC20, Initializable, and Math are used. The vault
is deployed behind an OpenZeppelin `TransparentUpgradeableProxy`; the proxy's
separate `ProxyAdmin` owns upgrades, while the fund's AccessControl roles keep
operating permissions separate. The implementation exposes no arbitrary-call
function.

Run locally:

```bash
cd contracts
forge install OpenZeppelin/openzeppelin-contracts --no-git --shallow
forge install foundry-rs/forge-std --no-git --shallow
forge test --offline -vvv
anvil
PRIVATE_KEY=... FUND_WETH_ADDRESS=0x0dd1df4fdd55808c9d530c9599bea5107f6b9b4e \
  forge script script/DeployFund.s.sol --rpc-url https://rpc.testnet.chain.robinhood.com \
  --chain-id 46630 --broadcast

# After reviewing the new implementation, upgrade the proxy later with:
PRIVATE_KEY=... FUND_CONTRACT_ADDRESS=0x<proxy> \
  forge script script/UpgradeFund.s.sol --rpc-url https://rpc.testnet.chain.robinhood.com \
  --chain-id 46630 --broadcast
```

For Robinhood Chain testnet, supply `FUND_RPC_URL`, `FUND_CHAIN_ID=46630`, a
deployer `PRIVATE_KEY`, and `FUND_WETH_ADDRESS=0x0dd1df4fdd55808c9d530c9599bea5107f6b9b4e`.
This address was verified on the testnet RPC to have deployed bytecode, symbol
`WETH`, and 18 decimals. The deployment script
does not import, deploy, or fall back to MockUSDC. MockUSDC remains only under
`contracts/src/mocks/` for isolated unit tests. The repository never contains
a private key and does not auto-deploy mainnet.

## Deployed testnet instance

An earlier Fruit Fly Capital vault was deployed directly on Robinhood Chain
testnet (chain ID `46630`) before proxy support was added:

- Legacy direct vault: `0xD8bFFba0f008696B11D609A7B9498ED61B2bdFdD`
- Accounting asset: WETH `0x0dd1df4fdd55808c9d530c9599bea5107f6b9b4e`
- Treasury/deployer: `0xB82c137b3062548FecB19D153040D7D4755e2165`
- Deployment transaction: `0xe634e1d5fa5bb147e0c56afcedf490fdca89610a2d2d1803432a9e995c8ea0ba`
- Explorer: https://explorer.testnet.chain.robinhood.com/tx/0xe634e1d5fa5bb147e0c56afcedf490fdca89610a2d2d1803432a9e995c8ea0ba

The deployment was verified by receipt status `0x1`, vault bytecode, and
constructor reads for the WETH asset, treasury, 18-decimal asset scale, and
`FFC` share symbol. No MockUSDC was deployed or used by this deployment. That
legacy address is not upgradeable; deploy a new proxy with `DeployFund.s.sol`
and use the printed proxy address as `FUND_CONTRACT_ADDRESS`.

### Current proxy deployment

The upgradeable deployment was broadcast to Robinhood Chain testnet on 2026-09-10:

- Proxy: `0x3550C6dE4e39172ba357AAA51aA11F2a15e3571B`
- Implementation: `0xc5304Fa8D401c894a794b74B3Ac88DE59A125205`
- ProxyAdmin: `0x1D6792349d7a23b0dac0D58eF6Ba43ea7DbCfe8e`
- Implementation transaction: `0x9cc76fe2bf6c1654c9690bb2cf0bbfe11f36fb087f5fdaef58ceb35ad90f6372`
- Proxy transaction: `0xe9e44198977aa0c4441d4bafbf7aa9c4fd98677f4f705d5b801d06efcf13fe0e`
- Explorer: [proxy transaction](https://explorer.testnet.chain.robinhood.com/tx/0xe9e44198977aa0c4441d4bafbf7aa9c4fd98677f4f705d5b801d06efcf13fe0e)

The local `FUND_CONTRACT_ADDRESS` now points to the proxy. The previous direct
deployment remains documented as a legacy instance and is not used for new
upgrades.

### Upgrade authority

`DeployFund.s.sol` deploys the implementation and transparent proxy in one
transaction sequence. The proxy constructor creates a dedicated
`ProxyAdmin`, initializes the vault through the proxy, and prints:

- proxy address — the only address the fund service and users should call;
- implementation address — replaceable code, not a user-facing fund address;
- `ProxyAdmin` address — owner-controlled upgrade authority.

The upgrade script reads the ERC-1967 admin slot, deploys the next
implementation, and calls `ProxyAdmin.upgradeAndCall`. Future implementations
must preserve storage order, retain the initializer lock, and append new state
only before the reserved storage gap. Put the ProxyAdmin owner behind a
multisig or timelock before holding meaningful funds: an upgrade authority can
change fund behavior and is therefore a critical custody key.

## Python fund package

`malecns.fund` owns the accounting and autonomous execution boundary:

- `FundLedger` is sqlite3-backed and keeps raw fund events, deposits,
  withdrawals, trades, positions, NAV snapshots, balances, and metadata.
- `PortfolioEngine` calculates NAV, NAV/share, cash, deployed value, P&L,
  chain allocation, and reconciliation without Zerion.
- `CMCValuationProvider` is an optional price source; `FakeValuationProvider`
  is used by tests. Quotes retain source/provenance and are never balance proof.
- `AutonomousTradingRuntime` maintains all sixteen 6.25% fly positions,
  behavior transitions, netted intents, P&L, idempotency, and reconciliation.
- `SimulationExecutionAdapter` fills automatically for the demo. The
  `MainnetExecutionAdapter` performs approval, quote, calldata, slippage,
  liquidity, gas, and nonce checks, then returns a prepared transaction to its
  caller.
- `QueueExecutionAdapter` writes netted fly decisions to a JSONL queue. The
  standalone `scripts/run_trade_executor.py` consumes that queue, repeats the
  execution checks, signs with the executor process's `PRIVATE_KEY`, broadcasts
  when explicitly enabled, and feeds real hashes into the existing RPC receipt
  and Blockscout reconciliation path.

Bootstrap only inspects configuration by default:

```bash
PYTHONPATH=src python -m malecns.fund.bootstrap_privy
PYTHONPATH=src python -m malecns.fund.bootstrap_privy --create
```

`--create` is an explicit wallet-creation operation. No secret is printed.
Configure a Privy policy before any testnet or live transaction and keep the
treasury address equal to the vault's `strategyTreasury`.

## Standalone execution service

The browser and brain server emit biological trade decisions; they do not need
to own the execution loop. Set `FUND_ADAPTER=queue` and start the brain server,
then run:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_trade_executor.py
```

This defaults to `prepare` mode. It consumes one JSONL record per netted
allocation, requests Uniswap calldata, and prints the prepared result. To
enable the separate signer/broadcaster process, run it with
`FUND_RUNNER_MODE=broadcast` and `FUND_RUNNER_CONFIRM_BROADCAST=true`.
The runner checks that `PRIVATE_KEY` controls `FUND_WALLET_ADDRESS`, submits
the raw transaction, polls `eth_getTransactionReceipt`, and records only real
transaction hashes as onchain executions. Simulation fills remain separate.

## Browser/API boundary

The existing `brain_server` accepts `fund_status_request`, `portfolio_request`,
and `trade_history_request`, and also feeds embodied swarm telemetry into the
autonomous runtime. `frontend/portfolio.html` is a realtime dashboard for the
sixteen allocations, target/actual wallet portfolio, events, attempts, and
pending rebalances. Empty or unconfigured state displays `—` rather than fake
production numbers.

The portfolio page can be deployed with the Three.js frontend to Vercel. The
stateful Python WebSocket brain/fund service must remain on a persistent
backend such as Render; Vercel only serves the static pages.
