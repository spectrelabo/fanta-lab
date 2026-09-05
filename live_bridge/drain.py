"""Safe-drain suggestions: bid up players we don't want to make rivals overpay safely.

Extracted in toto from fantabot domain/asta/drain.py.

Guarantees:
1. The cap is strictly below the player's worth to us (floored at 0).
2. We only propose a push while enough rivals are still contesting (min 2).
3. If player is in our plan, we never drain (we bid according to our target plan).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MIN_CONTESTERS = 2


@dataclass(frozen=True)
class DrainSuggestion:
    """A safe push: how high to bid on an unwanted player, and how contested he is."""

    player_id: str
    cap: int
    contesters: int


def safe_push_cap(our_value: float) -> int:
    """The highest safe bid: strictly below the player's worth to us (floored at 0)."""
    return max(0, int(our_value) - 1)


def suggest_push(
    player_id: str,
    *,
    our_value: float,
    current_price: int,
    contesters: int,
    in_our_plan: bool,
    min_contesters: int = DEFAULT_MIN_CONTESTERS,
) -> DrainSuggestion | None:
    """Propose a safe capped push, or None if it would not be safe or worthwhile.

    Returns None when:
    - The player is one we actually want (in_our_plan=True).
    - Too few rivals are contesting to carry the price (contesters < min_contesters).
    - Current price already meets or exceeds the safe cap.
    """
    if in_our_plan:
        return None
    if contesters < min_contesters:
        return None
    cap = safe_push_cap(our_value)
    if cap < current_price + 1:
        return None
    return DrainSuggestion(player_id=player_id, cap=cap, contesters=contesters)
