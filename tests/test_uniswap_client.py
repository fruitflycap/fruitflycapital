from malecns.market.uniswap_client import UniswapTradingClient


WALLET = "0x3333333333333333333333333333333333333333"
TOKEN_IN = "0x0000000000000000000000000000000000000000"
TOKEN_OUT = "0x1111111111111111111111111111111111111111"


def test_hosted_client_builds_robinhood_v4_multihop_quote_request(monkeypatch):
    client = UniswapTradingClient("secret", permit2_disabled=True)
    calls = []

    def fake_post(self, path, body):
        calls.append((path, body))
        return {"requestId": "req-1", "routing": "CLASSIC", "quote": {"output": {"amount": "987654"}}}

    monkeypatch.setattr(UniswapTradingClient, "_post", fake_post)
    quote = client.quote_exact_input(
        swapper=WALLET,
        token_in=TOKEN_IN,
        token_out=TOKEN_OUT,
        chain_id=4663,
        amount_in=1234,
        slippage_tolerance=0.5,
    )

    assert quote.amount_out == 987654
    assert calls == [
        (
            "/quote",
            {
                "swapper": WALLET,
                "tokenIn": TOKEN_IN,
                "tokenOut": TOKEN_OUT,
                "tokenInChainId": "4663",
                "tokenOutChainId": "4663",
                "amount": "1234",
                "type": "EXACT_INPUT",
                "slippageTolerance": 0.5,
                "routingPreference": "BEST_PRICE",
                "protocols": ["V2", "V3", "V4"],
            },
        )
    ]


def test_hosted_client_strips_null_permit_fields_before_swap(monkeypatch):
    client = UniswapTradingClient("secret", permit2_disabled=True)
    calls = []
    response = {
        "requestId": "req-1",
        "routing": "CLASSIC",
        "quote": {"output": {"amount": "987654"}},
        "permitData": None,
        "permitTransaction": None,
    }
    quote = type("Quote", (), {"response": response})()

    def fake_post(self, path, body):
        calls.append((path, body))
        return {"swap": {"to": TOKEN_OUT, "data": "0x1234", "value": "0"}}

    monkeypatch.setattr(UniswapTradingClient, "_post", fake_post)
    swap = client.create_swap_transaction(quote)

    assert swap["data"] == "0x1234"
    assert calls == [("/swap", {"requestId": "req-1", "routing": "CLASSIC", "quote": {"output": {"amount": "987654"}}})]


def test_hosted_client_uses_proxy_approval_flow(monkeypatch):
    client = UniswapTradingClient("secret", permit2_disabled=True)
    calls = []

    def fake_post(self, path, body):
        calls.append((path, body))
        return {"approval": {"to": TOKEN_OUT, "data": "0x095ea7b3", "value": "0"}, "cancel": None}

    monkeypatch.setattr(UniswapTradingClient, "_post", fake_post)
    result = client.check_approval_for_swap(wallet_address=WALLET, token=TOKEN_OUT, amount=500, chain_id=4663)

    assert result["approval"]["to"] == TOKEN_OUT
    assert calls == [("/check_approval", {"walletAddress": WALLET, "token": TOKEN_OUT, "amount": "500", "chainId": 4663})]
