from __future__ import annotations

import math
from collections.abc import Sequence


class FeatureNormalizer:
    """Bounded contextual normalizers; no future observations are accepted."""

    def normalize(
        self,
        value: float,
        method: str,
        *,
        history: Sequence[float] = (),
        scale: float = 1.0,
    ) -> float:
        numeric = float(value)
        prior = tuple(float(item) for item in history if math.isfinite(float(item)))
        if method == "signed":
            # Runtime normalized values always use the shared 0..1 contract;
            # signed direction is recovered by factor models as 2*n - 1.
            return (_signed_unit(numeric, scale) + 1.0) / 2.0
        if method == "bounded":
            return _clip(numeric)
        if method == "ratio_baseline":
            baseline = _median(prior) if prior else max(scale, 1e-9)
            return _clip(numeric / max(abs(baseline), 1e-9))
        if method == "stability":
            if len(prior) < 2:
                return 0.5 if prior else 0.0
            mean = max(abs(_median(prior)), 1e-9)
            deviation = sum(abs(item - _median(prior)) for item in prior) / len(prior)
            return _clip(1.0 - deviation / mean)
        if method == "log1p_relative":
            baseline = _median(prior) if prior else 0.0
            reference = max(abs(baseline), scale, 1e-9)
            return _clip(math.log1p(max(0.0, numeric)) / math.log1p(reference))
        if method == "log1p_absolute":
            return _clip(math.log1p(max(0.0, numeric)) / math.log1p(max(scale, 1e-9)))
        if method == "rank_inverse":
            # Lower CMC rank is better. Keep the signal bounded and avoid
            # treating rank as a price or return forecast.
            return _clip(1.0 / (1.0 + max(0.0, numeric - 1.0) / max(scale, 1e-9)))
        raise ValueError(f"unknown normalization method: {method}")


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _signed_unit(value: float, scale: float) -> float:
    return math.tanh(value / max(abs(scale), 1e-9))


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
