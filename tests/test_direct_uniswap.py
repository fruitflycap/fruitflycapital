from malecns.market.direct_uniswap import DirectRouteQuote, DirectUniswapClient
from malecns.fund.wallet import ZERO_ADDRESS


WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
TOKEN = "0x1111111111111111111111111111111111111111"
POOL = "0x2222222222222222222222222222222222222222"
WALLET = "0x3333333333333333333333333333333333333333"


def _word(value: int) -> str:
    return f"{value:064x}"


class FakeRpc:
    expected_chain_id = 4663

    def __init__(self):
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        data = params[0]["data"]
        selector = data[2:10]
        if selector == "1698ee82":
            return "0x" + _word(int(POOL, 16))
        if selector == "cdca1753":
            return "0x" + _word(987654)
        if selector == "dd62ed3e":
            return "0x" + _word(0)
        raise AssertionError(f"unexpected call selector {selector}")


def test_direct_client_quotes_v3_over_rpc_without_hosted_api(monkeypatch):
    monkeypatch.setenv("FUND_CHAIN_ID", "4663")
    monkeypatch.setenv("FUND_WETH_ADDRESS", WETH)
    rpc = FakeRpc()
    client = DirectUniswapClient.from_env(rpc)

    quote = client.quote(token_in=ZERO_ADDRESS, token_out=TOKEN, amount_in=1234)

    assert quote.kind == "v3"
    assert quote.pool == POOL
    assert quote.amount_out == 987654
    assert any(call[1][0]["data"].startswith("0xcdca1753") for call in rpc.calls)


def test_direct_client_builds_native_buy_and_token_sell_calldata():
    rpc = FakeRpc()
    client = DirectUniswapClient.from_env(rpc)
    buy = DirectRouteQuote("v3", ZERO_ADDRESS, TOKEN, 1000, 2000, 500, POOL)
    sell = DirectRouteQuote("v3", TOKEN, ZERO_ADDRESS, 1000, 2000, 500, POOL)

    buy_tx = client.build_swap(buy, recipient=WALLET, slippage_tolerance=0.5)
    sell_tx = client.build_swap(sell, recipient=WALLET, slippage_tolerance=0.5)

    assert buy_tx["to"].lower() == client.v3_router.lower()
    assert buy_tx["value"] == 1000
    assert buy_tx["data"].startswith("0x04e45aaf")
    assert sell_tx["data"].startswith("0x5ae401dc")
    assert sell_tx["value"] == 0


def test_direct_client_approval_targets_selected_router():
    rpc = FakeRpc()
    client = DirectUniswapClient.from_env(rpc)
    tx = client.approval_transaction(TOKEN, 500, route_kind="v2")

    assert tx["to"] == TOKEN
    assert client.v2_router[2:].lower() in tx["data"].lower()
