"""
Bayesian Fusion Model v3.0

Dirichlet-Multinomial conjugate model for combining:
- Model prior (Dixon-Coles probabilities)
- Market likelihood (odds-implied probabilities)

Core math preserved from v2.0 — just fixed imports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class BayesianUpdate:
    """Complete record of a Bayesian update."""
    prior: list[float]
    likelihood: list[float]
    prior_strength: int
    evidence_strength: int
    posterior: list[float]
    confidence_gain: float
    model_weight: float
    market_weight: float
    interpretation: str = ""


def bayesian_update(
    model_probs: list[float],
    market_probs: list[float],
    model_confidence: float = 0.5,
    market_margin: float = 0.05,
    market_dispersion: float = 0.04,
) -> BayesianUpdate:
    """Bayesian Dirichlet fusion of model and market probabilities.

    posterior[i] = (model_probs[i] × N + market_probs[i] × M) / (N + M)

    N = 10 + model_confidence × 50  (range 10–60)
    M = dynamic, driven by Pinnacle margin quality

    Key insight: tight Pinnacle margins (<2%) = high-quality signal → trust market more.
    Wide margins (>6%) = uncertain market → trust model more.

    v3.1: Market weight range widened from [4,22] to [5,45].
    At 1% margin: M≈45 → market gets ~55% weight when model is uncertain.
    At 6% margin: M≈8 → model dominates with ~83% weight.
    """
    # Prior strength N (model)
    N_raw = 10 + int(model_confidence * 50)
    N = max(8, min(65, N_raw))

    # Evidence strength M (market) — v3.1: more responsive to margin
    # margin_factor: 1.0 at 2% margin, 0.33 at 6% margin
    margin_factor = min(1.0, 0.02 / max(market_margin, 0.005))
    M_base = 5 + int(margin_factor * 40)  # range: 5–45
    consensus_factor = max(0.4, 1.0 - market_dispersion * 6)
    M = max(5, min(45, int(M_base * consensus_factor)))

    # Posterior
    total = N + M
    posterior = [
        round((model_probs[i] * N + market_probs[i] * M) / total, 4)
        for i in range(3)
    ]

    # Confidence gain
    confidence_gain = round(max(posterior) - max(model_probs), 4)

    # Interpretation
    interpretation = _interpret(
        model_confidence, market_margin, market_dispersion,
        N / total, M / total, confidence_gain
    )

    return BayesianUpdate(
        prior=model_probs,
        likelihood=market_probs,
        prior_strength=N,
        evidence_strength=M,
        posterior=posterior,
        confidence_gain=confidence_gain,
        model_weight=round(N / total, 3),
        market_weight=round(M / total, 3),
        interpretation=interpretation,
    )


def _interpret(
    model_conf: float, margin: float, dispersion: float,
    mw: float, mkw: float, gain: float,
) -> str:
    """Generate human-readable interpretation."""
    parts = [f"Model {mw:.0%} / Market {mkw:.0%}"]
    reasons = []

    if model_conf > 0.55:
        reasons.append("high model confidence → prior strengthened")
    elif model_conf < 0.40:
        reasons.append("low model confidence → market dominates")

    if margin < 0.03:
        reasons.append("low margin (quality signal)")
    elif margin > 0.06:
        reasons.append("high margin → market discounted")

    if dispersion > 0.07:
        reasons.append("high dispersion → market consensus weak")
    elif dispersion < 0.03:
        reasons.append("tight consensus → market signal strong")

    if reasons:
        parts.append("; ".join(reasons))
    if gain > 0.05:
        parts.append(f"→ confidence boosted +{gain:.0%}")
    elif gain < -0.03:
        parts.append(f"→ market pulled confidence down ({gain:.0%})")

    return " | ".join(parts)


def bayesian_fusion_predict(
    model_probs: list[float],
    market_odds: dict | None,
    model_confidence: float = 0.5,
) -> dict[str, Any]:
    """Convenience: single-call Bayesian fusion for one match.

    Args:
        model_probs: [p_home, p_draw, p_away] from DC model
        market_odds: {"home": 2.10, "draw": 3.50, "away": 3.80} or None
        model_confidence: 0–1 confidence in model

    Returns:
        Dict with posterior, weights, pick, interpretation
    """
    if market_odds:
        from models.odds import implied_probability
        imp = implied_probability(
            market_odds["home"], market_odds["draw"], market_odds["away"]
        )
        market_probs = [imp["home"], imp["draw"], imp["away"]]
        margin = imp["margin"]
        dispersion = 0.04  # default when only one bookmaker
    else:
        market_probs = model_probs[:]
        margin = 0.05
        dispersion = 0.04

    update = bayesian_update(
        model_probs, market_probs,
        model_confidence=model_confidence,
        market_margin=margin,
        market_dispersion=dispersion,
    )

    # Determine pick from posterior
    post = update.posterior
    pick_idx = max(range(3), key=lambda i: post[i])
    pick_label = ["Home Win", "Draw", "Away Win"][pick_idx]

    return {
        "posterior": {"home": post[0], "draw": post[1], "away": post[2]},
        "pick": pick_label,
        "confidence": round(max(post), 4),
        "model_weight": update.model_weight,
        "market_weight": update.market_weight,
        "interpretation": update.interpretation,
    }
