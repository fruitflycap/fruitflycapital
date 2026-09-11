from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    domain: str
    description: str
    unit: str
    value_type: str
    normalization_method: str
    directionality: str
    missing_value_policy: str = "unavailable"
    enabled: bool = True
    version: str = "features-v1"


def default_feature_registry() -> dict[str, FeatureDefinition]:
    """Stable registry for current features plus future provider slots."""

    definitions = [
        FeatureDefinition("market.volume5m", "market", "USD volume in the last five minutes", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.volume15m", "market", "USD volume in the last fifteen minutes", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.volume1h", "market", "USD volume in the last hour", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.volume24h", "market", "USD volume in the last 24 hours when supplied", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.marketCap", "market", "Circulating market cap when supplied by the provider", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.fdv", "market", "Fully diluted valuation when supplied by the provider", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.priceUsd", "market", "Token price in USD", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.pairAgeHours", "market", "Age of the selected liquidity pair", "hours", "number", "log1p_absolute", "positive"),
        FeatureDefinition("market.cmcRank", "market", "CoinMarketCap global rank when supplied", "rank", "number", "rank_inverse", "positive"),
        FeatureDefinition("market.circulatingSupply", "market", "Circulating supply when supplied", "tokens", "number", "log1p_relative", "positive"),
        FeatureDefinition("market.cmcPercentChange7d", "market", "CoinMarketCap seven-day price change", "%", "number", "signed", "signed"),
        FeatureDefinition("market.cmcVolumeChange24h", "market", "CoinMarketCap 24-hour volume change", "%", "number", "signed", "signed"),
        FeatureDefinition("market.marketCapDominance", "market", "Market-cap dominance when supplied", "%", "number", "log1p_absolute", "positive"),
        FeatureDefinition("flow.buyCount5m", "flow", "Buy transaction count in five minutes", "count", "number", "log1p_relative", "positive"),
        FeatureDefinition("flow.sellCount5m", "flow", "Sell transaction count in five minutes", "count", "number", "log1p_relative", "positive"),
        FeatureDefinition("flow.buyUsd5m", "flow", "Buy USD volume in five minutes", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("flow.sellUsd5m", "flow", "Sell USD volume in five minutes", "USD", "number", "log1p_relative", "positive"),
        FeatureDefinition("flow.imbalance", "flow", "Token-relative buy/sell USD imbalance", "ratio", "number", "signed", "signed"),
        FeatureDefinition("flow.txVelocity", "flow", "Unique transactions per minute", "tx/min", "number", "log1p_relative", "positive"),
        FeatureDefinition("flow.acceleration", "flow", "Change in transaction velocity", "tx/min2", "number", "signed", "signed"),
        FeatureDefinition("flow.buySellCountImbalance", "flow", "Token-relative count imbalance", "ratio", "number", "signed", "signed"),
        FeatureDefinition("flow.accelerationMagnitude", "flow", "Absolute transaction acceleration", "tx/min2", "number", "log1p_relative", "positive"),
        FeatureDefinition("liquidity.absolute", "liquidity", "Current executable pool liquidity", "USD", "number", "log1p_absolute", "positive"),
        FeatureDefinition("liquidity.relative", "liquidity", "Liquidity relative to prior observed liquidity", "ratio", "number", "ratio_baseline", "positive"),
        FeatureDefinition("liquidity.stability", "liquidity", "Stability of liquidity across observations", "ratio", "number", "stability", "positive"),
        FeatureDefinition("liquidity.volumeRatio", "liquidity", "One-hour volume divided by liquidity", "ratio", "number", "log1p_absolute", "positive"),
        FeatureDefinition("liquidity.marketCapToLiquidity", "liquidity", "Circulating market cap divided by pool liquidity", "ratio", "number", "log1p_absolute", "negative"),
        FeatureDefinition("liquidity.fdvToLiquidity", "liquidity", "FDV divided by pool liquidity", "ratio", "number", "log1p_absolute", "negative"),
        FeatureDefinition("liquidity.volume24hToMarketCap", "liquidity", "24-hour volume divided by circulating market cap", "ratio", "number", "log1p_absolute", "positive"),
        FeatureDefinition("liquidity.volume24hToLiquidity", "liquidity", "24-hour volume divided by pool liquidity", "ratio", "number", "log1p_absolute", "positive"),
        FeatureDefinition("valuation.marketCapLiquidityQuality", "valuation", "Bounded quality of market cap relative to executable liquidity", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("valuation.fdvLiquidityQuality", "valuation", "Bounded quality of FDV relative to executable liquidity", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("valuation.volumeToMarketCap", "valuation", "24-hour turnover relative to market cap", "ratio", "number", "log1p_absolute", "positive"),
        FeatureDefinition("valuation.volumeToLiquidity", "valuation", "24-hour turnover relative to executable liquidity", "ratio", "number", "log1p_absolute", "positive"),
        FeatureDefinition("holders.growth24h", "holders", "Holder growth over 24 hours", "ratio", "number", "signed", "signed"),
        FeatureDefinition("holders.concentrationQuality", "holders", "Quality inverse of holder concentration", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("holders.churnQuality", "holders", "Holder retention quality", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("security.contractVerified", "security", "Contract verification status", "boolean", "number", "bounded", "positive"),
        FeatureDefinition("security.sellable", "security", "Whether the represented token can be sold", "boolean", "number", "bounded", "positive"),
        FeatureDefinition("security.taxQuality", "security", "Quality after buy/sell tax checks", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("security.ownerRisk", "security", "Owner-control risk quality", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("social.sentiment", "social", "Provider sentiment signal", "ratio", "number", "signed", "signed"),
        FeatureDefinition("social.mentionAcceleration", "social", "Change in mention velocity", "mentions/min2", "number", "signed", "signed"),
        FeatureDefinition("onchain.transferVelocity", "onchain", "Transfer velocity", "tx/min", "number", "log1p_relative", "positive"),
        FeatureDefinition("onchain.uniqueWalletGrowth", "onchain", "Unique active wallet growth", "ratio", "number", "signed", "signed"),
        FeatureDefinition("fundamental.ageQuality", "fundamentals", "Token age quality", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("fundamental.supplyQuality", "fundamentals", "Supply characteristic quality", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("fundamental.protocolUsage", "fundamentals", "Protocol usage quality", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("risk.liquidityStress", "risk", "Stress from low executable liquidity", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("risk.flowInstability", "risk", "Instability from directional flow", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("risk.volatility", "risk", "Observed transaction-velocity volatility proxy", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("activity.volumeShock", "activity", "Current volume against expected five-minute volume", "ratio", "number", "bounded", "positive"),
        FeatureDefinition("activity.txAcceleration", "activity", "Transaction acceleration novelty", "tx/min2", "number", "signed", "signed"),
    ]
    return {item.feature_id: item for item in definitions}
