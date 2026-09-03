#!/usr/bin/env python3
"""
Spectre - FantaMoneyball — Personal Configuration Override (TEMPLATE)

Copy this file to `config.personal.py` and customize for your league.
config.personal.py is in .gitignore and will NEVER be committed to the public repo.

Any variable defined here will override the corresponding value in config_defaults.py.
"""

# ──────────────────────────────────────────────────────────────────────
# YOUR LEAGUE SETTINGS
# ──────────────────────────────────────────────────────────────────────

DEFAULT_BUDGET = 1000
DEFAULT_ROSTER_SLOTS = {"P": 4, "D": 9, "C": 9, "A": 7}  # 29-player roster

DEFAULT_TEAMS = [
    {"id": 1,  "name": "La Mia Squadra",  "is_me": True},
    {"id": 2,  "name": "Avversario 1",    "is_me": False},
    {"id": 3,  "name": "Avversario 2",    "is_me": False},
    {"id": 4,  "name": "Avversario 3",    "is_me": False},
    {"id": 5,  "name": "Avversario 4",    "is_me": False},
    {"id": 6,  "name": "Avversario 5",    "is_me": False},
    {"id": 7,  "name": "Avversario 6",    "is_me": False},
    {"id": 8,  "name": "Avversario 7",    "is_me": False},
    {"id": 9,  "name": "Avversario 8",    "is_me": False},
    {"id": 10, "name": "Avversario 9",    "is_me": False},
]

# Password for Battitore (auctioneer) admin mode
ADMIN_PASSWORD = "la_tua_password_segreta"
