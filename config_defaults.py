#!/usr/bin/env python3
"""
fanta-lab — Default Configuration for Community Open-Source Release.

These are the baseline defaults used when no personal configuration override
is present. They represent a standard 10-team, 500-credit, 25-slot league.

To customize for your personal league, copy `config.personal.example.py`
to `config.personal.py` and edit the values. That file is gitignored.
"""

# ──────────────────────────────────────────────────────────────────────
# LEAGUE DEFAULTS (Community Standard)
# ──────────────────────────────────────────────────────────────────────

DEFAULT_BUDGET = 500
DEFAULT_ROSTER_SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}  # 25-player roster
DEFAULT_NUM_TEAMS = 10

DEFAULT_TEAMS = [
    {"id": i, "name": f"Squadra {i}", "is_me": i == 1}
    for i in range(1, DEFAULT_NUM_TEAMS + 1)
]

# Admin password for Battitore (auctioneer) mode
ADMIN_PASSWORD = "fanta2026"
