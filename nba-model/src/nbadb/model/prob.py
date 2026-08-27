"""Probability helpers: American-odds conversion, devigging, and a normal
spread->win-probability model. These are the market-math primitives the edge
analysis is built on; kept pure and separately testable.
"""
from __future__ import annotations
import math

# NBA final-margin dispersion around its expectation. ~11-12 pts is the widely
# used value; it is the one free parameter turning a spread into a probability.
MARGIN_SD = 11.5


def implied_prob(american: float) -> float:
    """American odds -> implied probability (still contains the vig)."""
    return 100.0 / (american + 100) if american > 0 else abs(american) / (abs(american) + 100)


def american_to_decimal(american: float) -> float:
    return american / 100.0 + 1 if american > 0 else 100.0 / abs(american) + 1


def devig_two_way(a1: float, a2: float, method: str = "multiplicative"):
    """Two American prices on opposite sides -> (fair1, fair2, overround).

    'multiplicative' (a.k.a. normalization) just rescales the two vigged
    probabilities to sum to 1. It is the standard baseline; power/shin refine it
    but rarely flip a decision at these margins, which is why the schema records
    the method alongside the number.
    """
    p1, p2 = implied_prob(a1), implied_prob(a2)
    over = p1 + p2                       # > 1 by the overround (the vig)
    if method != "multiplicative":
        raise NotImplementedError(method)
    return p1 / over, p2 / over, over


def spread_to_win_prob(team_spread: float, sd: float = MARGIN_SD) -> float:
    """Closing spread (team perspective, negative = favored) -> P(team wins).

    Expected margin = -spread, so a -6 favorite is expected to win by 6; the
    win probability is the normal mass above 0.
    """
    return 0.5 * (1 + math.erf((-team_spread) / (sd * math.sqrt(2))))
