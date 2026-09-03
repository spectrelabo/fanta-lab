#!/usr/bin/env python3
"""
fanta-lab — Spectre - FantaMoneyball: Modern Quantitative Auction & Live Draft Platform for Fantacalcio Serie A
Clean, professional interface with local profile isolation, custom targets, FantaMoneyball AI query assistant, and Admin-gated Live Draft.
"""

import os
import sys
import json
import re
import pandas as pd
import requests
from flask import Flask, jsonify, request, render_template_string, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

DATA_PATH = os.path.join(BASE_DIR, "data", "dataset_finale.csv")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(BASE_DIR, "dataset_finale.csv")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(BASE_DIR, "examples", "dataset_sample.csv")

# Support writable temp path for Vercel / serverless environments
STATE_PATH = "/tmp/auction_state.json" if os.environ.get("VERCEL") else os.path.join(BASE_DIR, "auction_state.json")
SETTINGS_PATH = "/tmp/league_settings.json" if os.environ.get("VERCEL") else os.path.join(BASE_DIR, "league_settings.json")

# Load local .env if present
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────
# CASCADING CONFIGURATION LOADER
# Priority: config.personal.py > config_defaults.py > hardcoded fallback
# ──────────────────────────────────────────────────────────────────────

# Hardcoded fallback (always safe)
DEFAULT_BUDGET = 500
DEFAULT_ROSTER_SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
DEFAULT_TEAMS = [{"id": i, "name": f"Squadra {i}", "is_me": i == 1} for i in range(1, 11)]
ADMIN_PASSWORD = "fanta2026"

# Layer 1: Load community defaults
try:
    import config_defaults
    DEFAULT_BUDGET = getattr(config_defaults, "DEFAULT_BUDGET", DEFAULT_BUDGET)
    DEFAULT_ROSTER_SLOTS = getattr(config_defaults, "DEFAULT_ROSTER_SLOTS", DEFAULT_ROSTER_SLOTS)
    DEFAULT_TEAMS = getattr(config_defaults, "DEFAULT_TEAMS", DEFAULT_TEAMS)
    ADMIN_PASSWORD = getattr(config_defaults, "ADMIN_PASSWORD", ADMIN_PASSWORD)
except ImportError:
    pass

# Layer 2: Personal Profile Support
# 2a. Environment-based override (via PERSONAL_TEAMS_JSON or PERSONAL_TEAMS env var on private Vercel)
_env_teams_json = os.environ.get("PERSONAL_TEAMS_JSON")
if _env_teams_json:
    try:
        import json
        DEFAULT_TEAMS = json.loads(_env_teams_json)
    except Exception:
        pass
elif os.environ.get("PERSONAL_TEAMS"):
    # Comma-separated list of names: "Io,Squadra2,Squadra3,..."
    names = [n.strip() for n in os.environ.get("PERSONAL_TEAMS").split(",") if n.strip()]
    if names:
        DEFAULT_TEAMS = [{"id": i+1, "name": name, "is_me": i == 0} for i, name in enumerate(names)]

# 2b. File-based override (if config.personal.py is present locally, gitignored)
_personal_config_path = os.path.join(BASE_DIR, "config.personal.py")
if os.path.exists(_personal_config_path):
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location("config_personal", _personal_config_path)
        _personal = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_personal)
        DEFAULT_BUDGET = getattr(_personal, "DEFAULT_BUDGET", DEFAULT_BUDGET)
        DEFAULT_ROSTER_SLOTS = getattr(_personal, "DEFAULT_ROSTER_SLOTS", DEFAULT_ROSTER_SLOTS)
        DEFAULT_TEAMS = getattr(_personal, "DEFAULT_TEAMS", DEFAULT_TEAMS)
        ADMIN_PASSWORD = getattr(_personal, "ADMIN_PASSWORD", ADMIN_PASSWORD)
    except Exception:
        pass

# Environment variable override for admin password
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", ADMIN_PASSWORD)

TOTAL_ROSTER_SIZE = sum(DEFAULT_ROSTER_SLOTS.values())

# ──────────────────────────────────────────────────────────────────────
# BOT IDENTITY & PERSONA
# ──────────────────────────────────────────────────────────────────────
BOT_NAME = os.environ.get("BOT_NAME", "FantaMoneyball AI")
BOT_SUBTITLE = os.environ.get("BOT_SUBTITLE", "Assistente Tattico Quantitativo")
BOT_AVATAR_TEXT = os.environ.get("BOT_AVATAR_TEXT", "AI")
BOT_BADGE = os.environ.get("BOT_BADGE", "PRO DECISION")
BOT_GREETING = os.environ.get(
    "BOT_GREETING",
    "Ciao! Sono l'assistente quantitativo di **Spectre - FantaMoneyball**. Chiedimi confronti (es. *Malen vs Lautaro*), "
    "analisi di reparto o raccomandazioni basate su VORP e proiezioni ML."
)
BOT_AVATAR_IMAGE = os.environ.get("BOT_AVATAR_URL", "")

# Load overrides from gitignored config.personal.py if present locally
if os.path.exists(_personal_config_path):
    try:
        BOT_NAME = getattr(_personal, "BOT_NAME", BOT_NAME)
        BOT_SUBTITLE = getattr(_personal, "BOT_SUBTITLE", BOT_SUBTITLE)
        BOT_AVATAR_TEXT = getattr(_personal, "BOT_AVATAR_TEXT", BOT_AVATAR_TEXT)
        BOT_BADGE = getattr(_personal, "BOT_BADGE", BOT_BADGE)
        BOT_GREETING = getattr(_personal, "BOT_GREETING", BOT_GREETING)
    except Exception:
        pass

# Check local personal avatar if exists
_local_avatar_path = os.path.join(BASE_DIR, "static", "personal_avatar.jpg")
if os.path.exists(_local_avatar_path):
    try:
        import base64
        with open(_local_avatar_path, "rb") as f:
            BOT_AVATAR_IMAGE = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        pass

IS_PERSONAL = bool(BOT_AVATAR_IMAGE or os.path.exists(_personal_config_path) or os.environ.get("APP_ENV") == "personal")

app = Flask(__name__)


@app.after_request
def add_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ──────────────────────────────────────────────────────────────────────
# TACTICAL STRATEGY BLUEPRINTS (SCALA SLOT PRESETS)
# ──────────────────────────────────────────────────────────────────────

TACTICAL_PRESETS = {
    "trazione_anteriore": {
        "id": "trazione_anteriore",
        "name": "Trazione Anteriore (Top Bomber)",
        "badge": "ATT 65%",
        "description": "Investi il 65% in attacco (360-450 cr per 1 Top Bomber primario come Malen o Lautaro). Difesa a basso costo e centrocampo di regolaristi.",
        "split": {"P": "70 cr (7%)", "D": "90 cr (9%)", "C": "190 cr (19%)", "A": "650 cr (65%)"},
        "slots": {
            "A": [
                {"slot": 1, "name": "1° Slot: Top Bomber Assoluto (20+ Gol)", "target_budget": "360-450 cr", "max_limit": 470, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Secondo Attaccante / Spalla", "target_budget": "100-140 cr", "max_limit": 150, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Terzo Slot", "target_budget": "40-60 cr", "max_limit": 70, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Opportunità / Titolare", "target_budget": "10-25 cr", "max_limit": 30, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Copertura Reparto", "target_budget": "3-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Profilo a 1 cr", "target_budget": "1 cr", "max_limit": 3, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "C": [
                {"slot": 1, "name": "1° Slot: Centrocampista Semi-Top", "target_budget": "60-90 cr", "max_limit": 100, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare Affidabile", "target_budget": "35-55 cr", "max_limit": 60, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Regolarista", "target_budget": "20-35 cr", "max_limit": 40, "fascia": 3},
                {"slot": 4, "name": "4° Slot: Titolare Low-Cost", "target_budget": "10-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Titolare Squadra Media", "target_budget": "5-12 cr", "max_limit": 15, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Copertura", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Scommessa", "target_budget": "1-3 cr", "max_limit": 4, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "D": [
                {"slot": 1, "name": "1° Slot: Titolare Prima Fascia Difesa", "target_budget": "25-40 cr", "max_limit": 45, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare Sicuro", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Squadra Media", "target_budget": "10-18 cr", "max_limit": 20, "fascia": 3},
                {"slot": 4, "name": "4° Slot: Regolarista", "target_budget": "5-12 cr", "max_limit": 15, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Terzino Low Cost", "target_budget": "3-8 cr", "max_limit": 10, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Titolare Provincia", "target_budget": "1-5 cr", "max_limit": 6, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Copertura", "target_budget": "1 cr", "max_limit": 3, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "P": [
                {"slot": 1, "name": "1° Portiere: Titolare Fascia Media/Top", "target_budget": "60-80 cr", "max_limit": 85, "fascia": 1},
                {"slot": 2, "name": "2° Portiere: Riserva Blocco", "target_budget": "1-5 cr", "max_limit": 8, "fascia": 2},
                {"slot": 3, "name": "3° Portiere: Terzo Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 3},
                {"slot": 4, "name": "4° Portiere: Quarto Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ]
        }
    },
    "modificatore_ferro": {
        "id": "modificatore_ferro",
        "name": "Modificatore di Ferro (Difesa Top)",
        "badge": "DIF 22% / POR 13%",
        "description": "Massimizza il bonus modificatore con Portiere Top e 3 difensori da alta MV (Dimarco, Bastoni). Attacco solido a 3 punte senza svenarsi.",
        "split": {"P": "130 cr (13%)", "D": "220 cr (22%)", "C": "210 cr (21%)", "A": "440 cr (44%)"},
        "slots": {
            "D": [
                {"slot": 1, "name": "1° Slot: Top Modificatore / Assistman", "target_budget": "70-110 cr", "max_limit": 125, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Secondo Top Difesa", "target_budget": "45-65 cr", "max_limit": 75, "fascia": 1},
                {"slot": 3, "name": "3° Slot: Titolare Alta MV", "target_budget": "30-45 cr", "max_limit": 50, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Difensore Primaria Squadra", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 2},
                {"slot": 5, "name": "5° Slot: Titolare Sicuro", "target_budget": "8-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Terzino di Spinta", "target_budget": "4-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Titolare Low Cost", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "A": [
                {"slot": 1, "name": "1° Slot: Attaccante Semi-Top Primario", "target_budget": "180-230 cr", "max_limit": 250, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Secondo Attaccante da Bonus", "target_budget": "110-140 cr", "max_limit": 150, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Terzo Attaccante Titolare", "target_budget": "60-85 cr", "max_limit": 95, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Co-Titolare / Opportunità", "target_budget": "20-40 cr", "max_limit": 45, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Copertura Reparto", "target_budget": "5-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Scommessa a 1 cr", "target_budget": "1-4 cr", "max_limit": 5, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "C": [
                {"slot": 1, "name": "1° Slot: Centrocampista Semi-Top", "target_budget": "70-100 cr", "max_limit": 110, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare da Bonus", "target_budget": "40-60 cr", "max_limit": 70, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Regolarista Affidabile", "target_budget": "25-40 cr", "max_limit": 45, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Titolare Squadra Media", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Titolare Low-Cost", "target_budget": "8-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Copertura", "target_budget": "4-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Scommessa", "target_budget": "1-5 cr", "max_limit": 6, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "P": [
                {"slot": 1, "name": "1° Portiere: Top Portiere Squadra Scudetto", "target_budget": "100-130 cr", "max_limit": 135, "fascia": 1},
                {"slot": 2, "name": "2° Portiere: Riserva Blocco", "target_budget": "1-5 cr", "max_limit": 8, "fascia": 2},
                {"slot": 3, "name": "3° Portiere: Terzo Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 3},
                {"slot": 4, "name": "4° Portiere: Quarto Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ]
        }
    },
    "centrocampo_dominante": {
        "id": "centrocampo_dominante",
        "name": "Centrocampo Dominante (Doppio Top CEN)",
        "badge": "CEN 37%",
        "description": "Acquista 2 centrocampisti rigoristi/top da 8-12 gol (Calhanoglu, McTominay, Paz). Attacco formato da 3 titolari continui.",
        "split": {"P": "90 cr (9%)", "D": "120 cr (12%)", "C": "370 cr (37%)", "A": "420 cr (42%)"},
        "slots": {
            "C": [
                {"slot": 1, "name": "1° Slot: Top Centrocampista Primario (Piazzati/Rigorista)", "target_budget": "160-200 cr", "max_limit": 210, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Secondo Top Centrocampista", "target_budget": "110-140 cr", "max_limit": 150, "fascia": 1},
                {"slot": 3, "name": "3° Slot: Titolare Bonus Continuo", "target_budget": "35-50 cr", "max_limit": 60, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Regolarista Affidabile", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Titolare Squadra Media", "target_budget": "8-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Copertura", "target_budget": "4-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Profilo Emergente", "target_budget": "1-5 cr", "max_limit": 6, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "A": [
                {"slot": 1, "name": "1° Slot: Attaccante Semi-Top (Riferimento)", "target_budget": "180-220 cr", "max_limit": 240, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Secondo Attaccante Titolare", "target_budget": "100-130 cr", "max_limit": 140, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Terzo Attaccante da Bonus", "target_budget": "60-80 cr", "max_limit": 90, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Opportunità / Titolare", "target_budget": "20-35 cr", "max_limit": 40, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Copertura", "target_budget": "5-12 cr", "max_limit": 15, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Scommessa a 1 cr", "target_budget": "1-4 cr", "max_limit": 5, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "D": [
                {"slot": 1, "name": "1° Slot: Difensore Semi-Top", "target_budget": "35-50 cr", "max_limit": 55, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare Squadra Top", "target_budget": "20-30 cr", "max_limit": 35, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Sicuro", "target_budget": "12-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 4, "name": "4° Slot: Regolarista", "target_budget": "8-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Terzino Low Cost", "target_budget": "4-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Titolare Provincia", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Copertura", "target_budget": "1 cr", "max_limit": 3, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "P": [
                {"slot": 1, "name": "1° Portiere: Titolare Fascia Media/Top", "target_budget": "70-90 cr", "max_limit": 95, "fascia": 1},
                {"slot": 2, "name": "2° Portiere: Riserva Blocco", "target_budget": "1-5 cr", "max_limit": 8, "fascia": 2},
                {"slot": 3, "name": "3° Portiere: Terzo Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 3},
                {"slot": 4, "name": "4° Portiere: Quarto Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ]
        }
    },
    "moneyball_value": {
        "id": "moneyball_value",
        "name": "Equilibrata Moneyball (Profondità & Valore)",
        "badge": "EQUILIBRATA",
        "description": "Nessun giocatore oltre i 205 crediti. Massimizza il surplus di valore statistico e garantisce 29 titolari affidabili.",
        "split": {"P": "100 cr (10%)", "D": "160 cr (16%)", "C": "260 cr (26%)", "A": "480 cr (48%)"},
        "slots": {
            "A": [
                {"slot": 1, "name": "1° Slot: Attaccante 1° Livello Value", "target_budget": "150-195 cr", "max_limit": 205, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Secondo Attaccante Titolare", "target_budget": "120-155 cr", "max_limit": 165, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Terzo Attaccante Titolare", "target_budget": "90-120 cr", "max_limit": 130, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Quarto Attaccante / Titolare", "target_budget": "40-60 cr", "max_limit": 70, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Copertura Reparto", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Scommessa Giovane", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "C": [
                {"slot": 1, "name": "1° Slot: Centrocampista Leader", "target_budget": "80-110 cr", "max_limit": 120, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare Bonus", "target_budget": "60-85 cr", "max_limit": 95, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Continuo", "target_budget": "40-60 cr", "max_limit": 70, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Regolarista", "target_budget": "20-35 cr", "max_limit": 40, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Titolare Squadra Media", "target_budget": "12-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Copertura", "target_budget": "6-12 cr", "max_limit": 15, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Scommessa", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "D": [
                {"slot": 1, "name": "1° Slot: Difensore Top Modificatore", "target_budget": "40-60 cr", "max_limit": 65, "fascia": 2},
                {"slot": 2, "name": "2° Slot: Titolare Alta MV", "target_budget": "25-40 cr", "max_limit": 45, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Sicuro", "target_budget": "20-30 cr", "max_limit": 35, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Difensore Primaria Squadra", "target_budget": "12-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Regolarista", "target_budget": "8-15 cr", "max_limit": 18, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Terzino Low Cost", "target_budget": "4-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Titolare Provincia", "target_budget": "2-5 cr", "max_limit": 6, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "P": [
                {"slot": 1, "name": "1° Portiere: Titolare Blocco Solido", "target_budget": "80-100 cr", "max_limit": 105, "fascia": 1},
                {"slot": 2, "name": "2° Portiere: Riserva Blocco", "target_budget": "1-5 cr", "max_limit": 8, "fascia": 2},
                {"slot": 3, "name": "3° Portiere: Terzo Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 3},
                {"slot": 4, "name": "4° Portiere: Quarto Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ]
        }
    },
    "custom": {
        "id": "custom",
        "name": "Personalizzata (Custom)",
        "badge": "PERSONALIZZATA",
        "description": "Configura liberamente la suddivisione del budget per reparto e personalizza i tetti Stop-Loss e le fasce per ogni singolo slot.",
        "split": {"P": "80 cr (8%)", "D": "120 cr (12%)", "C": "250 cr (25%)", "A": "550 cr (55%)"},
        "slots": {
            "A": [
                {"slot": 1, "name": "1° Slot: Top Scorer Primario", "target_budget": "300-390 cr", "max_limit": 410, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Secondo Attaccante Titolare", "target_budget": "110-140 cr", "max_limit": 150, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Terzo Attaccante Titolare", "target_budget": "50-80 cr", "max_limit": 90, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Quarto Slot / Rotazione", "target_budget": "20-40 cr", "max_limit": 45, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Copertura Reparto", "target_budget": "10-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Scommessa", "target_budget": "2-6 cr", "max_limit": 8, "fascia": 4},
                {"slot": 7, "name": "7° Slot: Chiusura Reparto", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "C": [
                {"slot": 1, "name": "1° Slot: Top Centrocampista", "target_budget": "90-130 cr", "max_limit": 140, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Titolare Bonus", "target_budget": "50-80 cr", "max_limit": 90, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Titolare Squadra Media", "target_budget": "30-50 cr", "max_limit": 55, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Regolarista Continuo", "target_budget": "15-30 cr", "max_limit": 35, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Titolare Provincia", "target_budget": "10-20 cr", "max_limit": 25, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Copertura", "target_budget": "5-10 cr", "max_limit": 12, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Scommessa Giovane", "target_budget": "2-5 cr", "max_limit": 6, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "D": [
                {"slot": 1, "name": "1° Slot: Top Difensore Modificatore", "target_budget": "35-55 cr", "max_limit": 60, "fascia": 1},
                {"slot": 2, "name": "2° Slot: Titolare Alta MV", "target_budget": "20-35 cr", "max_limit": 40, "fascia": 2},
                {"slot": 3, "name": "3° Slot: Terzino di Spinta", "target_budget": "15-25 cr", "max_limit": 30, "fascia": 2},
                {"slot": 4, "name": "4° Slot: Centrale Affidabile", "target_budget": "10-18 cr", "max_limit": 20, "fascia": 3},
                {"slot": 5, "name": "5° Slot: Regolarista", "target_budget": "6-12 cr", "max_limit": 15, "fascia": 3},
                {"slot": 6, "name": "6° Slot: Titolare Low Cost", "target_budget": "3-8 cr", "max_limit": 10, "fascia": 3},
                {"slot": 7, "name": "7° Slot: Copertura", "target_budget": "1-4 cr", "max_limit": 5, "fascia": 4},
                {"slot": 8, "name": "8° Slot: Riserva", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
                {"slot": 9, "name": "9° Slot: Chiusura", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ],
            "P": [
                {"slot": 1, "name": "1° Portiere: Titolare Blocco Primario", "target_budget": "60-80 cr", "max_limit": 85, "fascia": 1},
                {"slot": 2, "name": "2° Portiere: Riserva Blocco", "target_budget": "1-3 cr", "max_limit": 5, "fascia": 2},
                {"slot": 3, "name": "3° Portiere: Terzo Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 3},
                {"slot": 4, "name": "4° Portiere: Quarto Portiere", "target_budget": "1 cr", "max_limit": 2, "fascia": 4},
            ]
        }
    }
}

DEFAULT_TACTIC_ID = "trazione_anteriore"


def load_dataset():
    """Loads player dataset and assigns VORP value tiers."""
    df = pd.read_csv(DATA_PATH)

    def assign_fascia(row):
        fvm = row.get("FVM_1000", 0)
        role = row["role"]
        if role == "A":
            if fvm >= 240: return 1
            elif fvm >= 95: return 2
            elif fvm >= 45: return 3
            else: return 4
        elif role == "C":
            if fvm >= 140: return 1
            elif fvm >= 60: return 2
            elif fvm >= 25: return 3
            else: return 4
        elif role == "D":
            if fvm >= 80: return 1
            elif fvm >= 40: return 2
            elif fvm >= 15: return 3
            else: return 4
        else:  # P
            if fvm >= 40: return 1
            elif fvm >= 10: return 2
            else: return 3

    df["fascia"] = df.apply(assign_fascia, axis=1)
    return df


def load_league_settings():
    """Load league settings from file, or return defaults from config cascade."""
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
                # Validate structure
                if "budget" in settings and "roster_slots" in settings and "teams" in settings:
                    return settings
        except Exception:
            pass
    # Return defaults from config cascade
    return {
        "budget": DEFAULT_BUDGET,
        "roster_slots": DEFAULT_ROSTER_SLOTS,
        "teams": DEFAULT_TEAMS
    }


def save_league_settings(settings):
    """Persist league settings to file."""
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_initial_state():
    """Creates a fresh auction state based on current league settings."""
    settings = load_league_settings()
    budget = settings["budget"]
    roster_slots = settings["roster_slots"]
    teams_cfg = settings["teams"]
    total_size = sum(roster_slots.values())

    teams = []
    for t in teams_cfg:
        teams.append({
            "id": t["id"],
            "name": t["name"],
            "is_me": t.get("is_me", False),
            "budget": budget,
            "spent": 0,
            "spent_by_role": {"P": 0, "D": 0, "C": 0, "A": 0},
            "remaining": budget,
            "roster": [],
            "counts": {"P": 0, "D": 0, "C": 0, "A": 0},
            "slots_left": dict(roster_slots),
            "total_slots_left": total_size,
            "max_bid": budget - (total_size - 1)
        })

    return {
        "budget_total": budget,
        "roster_structure": dict(roster_slots),
        "teams": teams,
        "assigned_players": {},
        "favorites": [],
        "history": []
    }


def load_state():
    """Load auction state from file. Accepts any valid structure regardless of budget/slot values."""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                # Validate structure (not specific values — any budget/slot combo is valid)
                if isinstance(state.get("teams"), list) and isinstance(state.get("assigned_players"), dict):
                    # Ensure roster_structure exists (backfill for old states)
                    if "roster_structure" not in state:
                        state["roster_structure"] = load_league_settings()["roster_slots"]
                    if "budget_total" not in state:
                        state["budget_total"] = load_league_settings()["budget"]
                    return state
        except Exception:
            pass
    return get_initial_state()


def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def recalculate_team_metrics(team, budget_total, roster_structure=None):
    """Recomputes counts, department expenditures, remaining funds and allowable max bid."""
    if roster_structure is None:
        roster_structure = load_league_settings()["roster_slots"]

    counts = {"P": 0, "D": 0, "C": 0, "A": 0}
    spent_by_role = {"P": 0, "D": 0, "C": 0, "A": 0}
    spent = 0
    for p in team["roster"]:
        r = p.get("role", "C")
        p_price = int(p.get("price", 1))
        counts[r] = counts.get(r, 0) + 1
        spent += p_price
        spent_by_role[r] = spent_by_role.get(r, 0) + p_price

    slots_left = {
        "P": max(0, roster_structure.get("P", 3) - counts["P"]),
        "D": max(0, roster_structure.get("D", 8) - counts["D"]),
        "C": max(0, roster_structure.get("C", 8) - counts["C"]),
        "A": max(0, roster_structure.get("A", 6) - counts["A"])
    }
    total_slots_left = sum(slots_left.values())
    remaining = budget_total - spent

    if total_slots_left > 0:
        max_bid = max(1, remaining - (total_slots_left - 1))
    else:
        max_bid = 0

    team["spent"] = spent
    team["spent_by_role"] = spent_by_role
    team["remaining"] = remaining
    team["counts"] = counts
    team["slots_left"] = slots_left
    team["total_slots_left"] = total_slots_left
    team["max_bid"] = max_bid


# ──────────────────────────────────────────────────────────────────────
# REST API ENDPOINTS
# ──────────────────────────────────────────────────────────────────────

@app.route("/static/<path:path>")
def send_static(path):
    return send_from_directory(os.path.join(BASE_DIR, "static"), path)



@app.route("/api/settings")
def api_get_settings():
    """Return current league settings (budget, slots, teams)."""
    settings = load_league_settings()
    return jsonify({"settings": settings})


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    """Save league settings from UI. Resets auction state if budget/slots changed."""
    data = request.json or {}
    budget = int(data.get("budget", DEFAULT_BUDGET))
    roster_slots = data.get("roster_slots", DEFAULT_ROSTER_SLOTS)
    teams_raw = data.get("teams", DEFAULT_TEAMS)

    # Validate
    if budget < 100 or budget > 5000:
        return jsonify({"error": "Budget deve essere tra 100 e 5000 crediti"}), 400
    for role in ["P", "D", "C", "A"]:
        if int(roster_slots.get(role, 0)) < 1:
            return jsonify({"error": f"Almeno 1 slot per il ruolo {role}"}), 400
    if len(teams_raw) < 2 or len(teams_raw) > 16:
        return jsonify({"error": "Numero squadre deve essere tra 2 e 16"}), 400

    # Normalize roster_slots to int
    roster_slots = {k: int(v) for k, v in roster_slots.items()}

    # Build clean teams list
    teams = []
    for i, t in enumerate(teams_raw):
        teams.append({
            "id": t.get("id", i + 1),
            "name": str(t.get("name", f"Squadra {i+1}")).strip() or f"Squadra {i+1}",
            "is_me": bool(t.get("is_me", i == 0))
        })

    new_settings = {"budget": budget, "roster_slots": roster_slots, "teams": teams}

    # Check if structural change requires state reset
    old_settings = load_league_settings()
    needs_reset = (
        old_settings["budget"] != budget or
        old_settings["roster_slots"] != roster_slots or
        len(old_settings["teams"]) != len(teams)
    )

    save_league_settings(new_settings)

    if needs_reset:
        # Reset auction state with new settings
        new_state = get_initial_state()
        save_state(new_state)
        return jsonify({"success": True, "reset": True, "message": "Impostazioni salvate. Asta resettata per nuova configurazione."})

    return jsonify({"success": True, "reset": False, "message": "Impostazioni salvate."})


@app.route("/api/auth_admin", methods=["POST"])
def api_auth_admin():
    data = request.json or {}
    pwd = str(data.get("password", "")).strip()
    if pwd == ADMIN_PASSWORD:
        return jsonify({"success": True, "is_admin": True})
    return jsonify({"error": "Password errata"}), 401


def compute_market_inflation(df, state):
    """Computes dynamic market inflation index comparing discretionary budget to remaining unassigned VORP."""
    assigned = state.get("assigned_players", {})
    assigned_keys = set(assigned.keys())
    teams = state.get("teams", [])
    total_remaining = sum(t.get("remaining", 0) for t in teams)
    total_slots_left = sum(t.get("total_slots_left", 0) for t in teams)
    discretionary_credits = max(0, total_remaining - total_slots_left)

    unassigned_df = df[~df["player"].isin(assigned_keys)]
    unassigned_vorp = float(unassigned_df["vorp_points"].clip(lower=0).sum())

    total_league_budget = state.get("budget_total", DEFAULT_BUDGET) * max(1, len(teams))
    roster_structure = state.get("roster_structure", DEFAULT_ROSTER_SLOTS)
    total_league_slots = sum(roster_structure.values()) * max(1, len(teams))
    initial_discretionary = max(1, total_league_budget - total_league_slots)
    initial_total_vorp = float(df["vorp_points"].clip(lower=0).sum()) or 1.0
    initial_ratio = initial_discretionary / initial_total_vorp

    current_ratio = discretionary_credits / max(1.0, unassigned_vorp)
    raw_inflation = current_ratio / max(0.001, initial_ratio)
    inflation_index = round(max(0.5, min(3.0, float(raw_inflation))), 2)

    if inflation_index >= 1.25:
        status = "SURRISCALDATO"
        desc = "Forte inflazione: i top costano oltre il Fair Price. Cerca value picks e attendi."
        color = "red"
    elif inflation_index >= 1.05:
        status = "INFLAZIONATO"
        desc = "Leggera inflazione: prezzi leggermente sopra la parità teorica."
        color = "yellow"
    elif inflation_index <= 0.85:
        status = "DEFLAZIONATO"
        desc = "Occasioni sul mercato! Tanti crediti spesi e molto VORP libero."
        color = "green"
    else:
        status = "EQUILIBRATO"
        desc = "Mercato in perfetto equilibrio con le stime teoriche."
        color = "blue"

    return {
        "index": inflation_index,
        "status": status,
        "description": desc,
        "color": color,
        "discretionary_credits": discretionary_credits,
        "unassigned_vorp": round(unassigned_vorp, 1)
    }


@app.route("/api/players")
def api_players():
    df = load_dataset()
    state = load_state()
    assigned = state.get("assigned_players", {})
    favorites = set(state.get("favorites", []))

    budget_scale = state.get("budget_total", DEFAULT_BUDGET) / 1000.0
    market_info = compute_market_inflation(df, state)
    inflation_factor = market_info["index"]

    role_filter = request.args.get("role")
    fascia_filter = request.args.get("fascia")
    only_available = request.args.get("available", "false").lower() == "true"
    search = request.args.get("q", "").strip().lower()

    records = []
    for _, row in df.iterrows():
        p_name = row["player"]
        is_assigned = p_name in assigned

        if only_available and is_assigned:
            continue
        if role_filter and role_filter != "ALL" and row["role"] != role_filter:
            continue
        if fascia_filter and fascia_filter != "ALL" and str(row["fascia"]) != str(fascia_filter):
            continue
        if search and search not in p_name.lower() and search not in str(row.get("team", "")).lower():
            continue

        fair_1000 = int(row.get("prezzo_fair_1000", 1))
        fair_scaled = max(1, int(round(fair_1000 * budget_scale)))
        fair_live = max(1, int(round(fair_scaled * inflation_factor)))

        assignment_info = assigned.get(p_name)
        records.append({
            "player": p_name,
            "role": row["role"],
            "role_mantra": str(row.get("role_mantra", "")),
            "team": str(row.get("team", "")),
            "price_official": int(row.get("Prezzo_Consigliato_Cr", 1)),
            "price_fair_1000": fair_1000,
            "price_fair_500": int(row.get("prezzo_fair_500", 1)),
            "price_fair_scaled": fair_scaled,
            "price_fair_live": fair_live,
            "surplus_value": int(row.get("surplus_value_cr", 0)),
            "score": float(row.get("score_composito", 0)),
            "pts_exp": float(row.get("predicted_pts_p50", 0)),
            "pts_floor": float(row.get("predicted_pts_p10", 0)),
            "pts_ceil": float(row.get("predicted_pts_p90", 0)),
            "pts_spread": float(row.get("pts_volatility_spread", 0)),
            "vorp": float(row.get("vorp_points", 0)),
            "injury_days": int(row.get("giorni_infortunio_3y", 0)),
            "injury_malus": float(row.get("malus_infortuni", 0)),
            "fascia": int(row["fascia"]),
            "is_starter_2627": bool(row.get("is_starter_2627", False)),
            "starts_2627": int(row.get("starts_2627", 0)),
            "minutes_2627": int(row.get("minutes_2627", 0)),
            "xg_3y": float(row.get("xg_media_3y", 0)) if pd.notna(row.get("xg_media_3y")) else None,
            "xa_3y": float(row.get("xa_media_3y", 0)) if pd.notna(row.get("xa_media_3y")) else None,
            "is_assigned": is_assigned,
            "assignment": assignment_info,
            "is_favorite": p_name in favorites
        })

    return jsonify({
        "players": records,
        "total": len(records),
        "tactical_presets": TACTICAL_PRESETS,
        "default_tactic": DEFAULT_TACTIC_ID,
        "market_index": market_info,
        "budget_scale": budget_scale
    })


@app.route("/api/state")
def api_state():
    state = load_state()
    df = load_dataset()
    assigned = state.get("assigned_players", {})

    for t in state["teams"]:
        recalculate_team_metrics(t, state["budget_total"], state.get("roster_structure"))

    scarcity = {}
    for role in ["P", "D", "C", "A"]:
        scarcity[role] = {1: 0, 2: 0, 3: 0, 4: 0}
        sub = df[df["role"] == role]
        for _, r in sub.iterrows():
            if r["player"] not in assigned:
                f = int(r["fascia"])
                scarcity[role][f] = scarcity[role].get(f, 0) + 1

    market_info = compute_market_inflation(df, state)

    return jsonify({
        "state": state,
        "scarcity": scarcity,
        "tactical_presets": TACTICAL_PRESETS,
        "default_tactic": DEFAULT_TACTIC_ID,
        "market_index": market_info
    })


@app.route("/api/sync_state", methods=["POST"])
def api_sync_state():
    client_state = request.json or {}
    if "teams" in client_state and "assigned_players" in client_state:
        for t in client_state["teams"]:
            recalculate_team_metrics(t, client_state.get("budget_total", DEFAULT_BUDGET), client_state.get("roster_structure"))
        save_state(client_state)
        return jsonify({"success": True})
    return jsonify({"error": "Invalid state structure"}), 400


@app.route("/api/assign", methods=["POST"])
def api_assign():
    data = request.json or {}
    player_name = data.get("player")
    team_id = int(data.get("team_id", 1))
    price = int(data.get("price", 1))

    if not player_name:
        return jsonify({"error": "Specificare il calciatore"}), 400

    df = load_dataset()
    p_match = df[df["player"] == player_name]
    if p_match.empty:
        return jsonify({"error": "Calciatore non presente nel database"}), 404

    p_row = p_match.iloc[0]
    state = load_state()

    team = next((t for t in state["teams"] if t["id"] == team_id), None)
    if not team:
        return jsonify({"error": "Squadra non trovata"}), 404

    role = p_row["role"]
    roster_structure = state.get("roster_structure", DEFAULT_ROSTER_SLOTS)
    max_slots_for_role = roster_structure.get(role, 3)

    if team["counts"][role] >= max_slots_for_role:
        return jsonify({"error": f"{team['name']} ha già completato i {max_slots_for_role} slot per il ruolo {role}."}), 400

    if price > team["max_bid"] and team["total_slots_left"] > 1:
        return jsonify({"error": f"Offerta ({price} cr) superiore al limite massimo consentito per {team['name']} ({team['max_bid']} cr)."}), 400

    player_item = {
        "player": player_name,
        "role": role,
        "team": str(p_row.get("team", "")),
        "price": price,
        "pts_exp": float(p_row.get("predicted_pts_p50", 0)),
        "score": float(p_row.get("score_composito", 0))
    }

    team["roster"].append(player_item)
    state["assigned_players"][player_name] = {
        "team_id": team_id,
        "team_name": team["name"],
        "price": price
    }

    state["history"].append({
        "action": "assign",
        "player": player_name,
        "team_id": team_id,
        "price": price
    })

    recalculate_team_metrics(team, state["budget_total"], state.get("roster_structure"))
    save_state(state)

    return jsonify({"success": True, "state": state})


@app.route("/api/undo", methods=["POST"])
def api_undo():
    state = load_state()
    if not state.get("history"):
        return jsonify({"error": "Nessuna operazione registrata da annullare"}), 400

    last_action = state["history"].pop()
    player_name = last_action["player"]
    team_id = last_action["team_id"]

    if player_name in state["assigned_players"]:
        del state["assigned_players"][player_name]

    team = next((t for t in state["teams"] if t["id"] == team_id), None)
    if team:
        team["roster"] = [p for p in team["roster"] if p["player"] != player_name]
        recalculate_team_metrics(team, state["budget_total"], state.get("roster_structure"))

    save_state(state)
    return jsonify({"success": True, "undone": last_action, "state": state})


@app.route("/api/ai_status", methods=["GET"])
def api_ai_status():
    """Returns AI Copilot diagnostic status and active engine."""
    try:
        from copilot import get_copilot_diagnostics
        diag = get_copilot_diagnostics()
        return jsonify(diag)
    except Exception as e:
        return jsonify({"error": str(e), "has_llm": False, "active_engine": "Fallback Matematico Offline"})


@app.route("/api/ai_test", methods=["GET", "POST"])
def api_ai_test():
    """Live diagnostic ping to each configured AI provider with HTTP status codes."""
    try:
        from copilot import test_all_providers
        return jsonify(test_all_providers())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai_query", methods=["POST"])
def api_ai_query():
    """
    FantaMoneyball AI Tactical Engine
    Priorità: Ollama locale -> OpenAI-compatible -> Google Gemini -> Local Quantitative Reasoner.
    """
    data = request.json or {}
    prompt = str(data.get("prompt", "")).strip()
    profile_id = int(data.get("profile_id", 1))

    if not prompt:
        return jsonify({"error": "Prompt vuoto"}), 400

    df = load_dataset()
    state = load_state()
    assigned = state.get("assigned_players", {})
    team = next((t for t in state["teams"] if t["id"] == profile_id), state["teams"][0])
    spent = team.get("spent_by_role", {"P": 0, "D": 0, "C": 0, "A": 0})
    counts = team.get("counts", {"P": 0, "D": 0, "C": 0, "A": 0})

    prompt_lower = prompt.lower()

    # ─────────────────────────────────────────────────────────────
    # 1. MODULAR COPILOT INTEGRATION (Ollama / OpenAI / Gemini)
    # ─────────────────────────────────────────────────────────────
    try:
        from copilot import get_copilot_response
        unassigned_df = df[~df['player'].isin(assigned.keys())]

        # Dynamic contextual sampling based on user query
        sample_df = unassigned_df.copy()
        
        # 1. Role filtering if requested
        role_map_kw = {'portier': 'P', 'difensor': 'D', 'centrocampist': 'C', 'attaccant': 'A'}
        for r_key, r_code in role_map_kw.items():
            if r_key in prompt_lower:
                sample_df = sample_df[sample_df['role'] == r_code]
                break

        # 2. Team filtering if requested
        team_kw = {
            'como': 'COM', 'milan': 'MIL', 'juve': 'JUV', 'juventus': 'JUV',
            'inter': 'INT', 'roma': 'ROM', 'lazio': 'LAZ', 'atalanta': 'ATA',
            'napoli': 'NAP', 'bologna': 'BOL', 'fiorentina': 'FIO', 'torino': 'TOR',
            'genoa': 'GEN', 'lecce': 'LEC', 'udinese': 'UDI', 'parma': 'PAR',
            'sassuolo': 'SAS', 'monza': 'MON', 'venezia': 'VEN', 'cagliari': 'CAG'
        }
        for t_k, t_c in team_kw.items():
            if re.search(rf'\b{re.escape(t_k)}\b', prompt_lower):
                sample_df = sample_df[sample_df['team'] == t_c]
                break

        # 3. Low-cost / "a 1" / budget filtering
        is_low_cost = any(term in prompt_lower for term in ["a 1", "1 credito", "1 cr", "low cost", "scommess", "economici", "risparmi", "prezzo basso", "meno di 5", "sotto i 5"])
        if is_low_cost:
            sample_df = sample_df[sample_df['prezzo_fair_1000'] <= 10].sort_values(
                ['is_starter_2627', 'predicted_pts_p50', 'vorp_points'], ascending=[False, False, False]
            )
        else:
            sample_df = sample_df.sort_values(['is_starter_2627', 'vorp_points'], ascending=[False, False])

        if sample_df.empty:
            sample_df = unassigned_df.sort_values('vorp_points', ascending=False)

        top_sample = sample_df.head(35)[['player', 'role', 'team', 'predicted_pts_p50', 'prezzo_fair_1000', 'vorp_points', 'is_starter_2627']].to_dict(orient='records')
        team_context = {
            "name": team["name"],
            "remaining": team["remaining"],
            "max_bid": team["max_bid"],
            "counts": counts,
            "spent_by_role": spent,
            "roster_structure": state.get("roster_structure", DEFAULT_ROSTER_SLOTS)
        }
        llm_reply = get_copilot_response(
            prompt, team_context, top_sample,
            budget_total=state.get("budget_total", DEFAULT_BUDGET),
            is_personal=IS_PERSONAL
        )
        if llm_reply:
            return jsonify(llm_reply)
    except Exception as e:
        print(f"Copilot exception: {e}")

    # ─────────────────────────────────────────────────────────────
    # 2. LOCAL QUANTITATIVE REASONING ENGINE (Zero Latency & 0 Cost)
    # ─────────────────────────────────────────────────────────────

    # A. Check for Squad Health / Roster Diagnostic
    squad_keywords = ["squadra", "rosa", "come sono", "cosa mi manca", "situazione", "budget", "bilancio", "diagnosi"]
    if any(k in prompt_lower for k in squad_keywords) and not any(p_name in prompt_lower for p_name in df['player'].str.lower().head(100)):
        p_slots = 4 - counts.get('P', 0)
        d_slots = 9 - counts.get('D', 0)
        c_slots = 9 - counts.get('C', 0)
        a_slots = 7 - counts.get('A', 0)
        tot_free = p_slots + d_slots + c_slots + a_slots
        avg_cr_per_slot = round(team['remaining'] / max(1, tot_free), 1)

        advice_points = []
        if a_slots > 0 and team['remaining'] > 300:
            advice_points.append(f"Riserva circa il 40-48% del budget residuo ({int(team['remaining']*0.45)} cr) per completare il reparto d'attacco con almeno 1 Top e 1 Semi-Top.")
        if d_slots > 3:
            advice_points.append(f"Mancano {d_slots} difensori. Se punti al Modificatore, investi su 2 centrali da 6.20+ MV a 15-25 cr e completa con titolari a 1-3 cr.")
        if c_slots > 3:
            advice_points.append(f"A centrocampo hai {c_slots} slot liberi: cerca profili con VORP positivo e xG alto (rigoristi/incursori).")
        if avg_cr_per_slot < 6:
            advice_points.append("ATTENZIONE: Media crediti per slot molto bassa. Procedi con disciplina chiamando solo svincolati a 1 credito.")

        return jsonify({
            "type": "roster_diagnostic",
            "title": f"Diagnosi Tattica: {team['name']}",
            "engine": "Regole Tattiche Locali (Offline)",
            "stats": {
                "remaining": team['remaining'],
                "max_bid": team['max_bid'],
                "free_slots": {"P": p_slots, "D": d_slots, "C": c_slots, "A": a_slots, "total": tot_free},
                "spent_by_role": spent,
                "avg_per_slot": avg_cr_per_slot
            },
            "advice": advice_points,
            "verdict": f"Stato Finanziario: Ti restano {team['remaining']} cr per {tot_free} slot (media {avg_cr_per_slot} cr/slot). Max rilancio disponibile: {team['max_bid']} cr."
        })

    aliases = {
        'lautaro': 'martinez l.',
        'lautaro martinez': 'martinez l.',
        'kvara': 'kvaratskhelia',
        'calha': 'calhanoglu',
        'chalanoglu': 'calhanoglu',
        'dimash': 'dimarco',
        'douglas': 'douglas luiz',
    }
    expanded_prompt = prompt_lower
    for k_alias, v_target in aliases.items():
        if k_alias in expanded_prompt:
            expanded_prompt += f" {v_target}"

    def player_matches_query(p_name_str, query_str):
        p_clean = p_name_str.lower()
        if p_clean in query_str:
            return True
        tokens = [t for t in re.split(r'[\s\.\-]+', p_clean) if len(t) >= 4]
        for tok in tokens:
            if re.search(rf'\b{re.escape(tok)}\b', query_str):
                return True
        return False

    # B. Multi-Player Comparison (2 or more players)
    is_comp = any(w in prompt_lower for w in ["vs", "contro", "confront", "meglio tra", "differenza tra", "chi tra", "chi prendere tra"])
    if is_comp:
        matched_players = []
        for _, row in df.iterrows():
            if player_matches_query(row['player'], expanded_prompt):
                if row['player'] not in [m['player'] for m in matched_players]:
                    matched_players.append(row)
            if len(matched_players) >= 3:
                break

        if len(matched_players) >= 2:
            matched_players = matched_players[:2] if len(re.split(r'\s+(?:vs|contro|e|o)\s+', prompt_lower)) <= 2 else matched_players[:3]
            matched_players.sort(key=lambda r: float(r.get('vorp_points', 0)), reverse=True)
            winner = matched_players[0]
            
            p_list = []
            for r in matched_players:
                p_list.append({
                    "name": r['player'], "team": r['team'], "role": r['role'],
                    "pts_exp": float(r.get('predicted_pts_p50', 0)),
                    "fair_1000": int(r.get('prezzo_fair_1000', 1)),
                    "vorp": float(r.get('vorp_points', 0)),
                    "starts": int(r.get('starts_2627', 0)),
                    "injury_days": int(r.get('giorni_infortunio_3y', 0))
                })

            return jsonify({
                "type": "comparison",
                "title": f"Confronto: {' vs '.join([p['name'] for p in p_list])}",
                "engine": "Regole Tattiche Locali (Offline)",
                "players": p_list,
                "winner": winner['player'],
                "verdict": f"Scelta Consigliata: **{winner['player']}** è il profilo con efficienza superiore (+{winner.get('vorp_points', 0):.1f} VORP, {winner.get('predicted_pts_p50', 0):.1f} pts attesi, Prezzo Fair: {int(winner.get('prezzo_fair_1000', 1))} cr)."
            })

    # C. Specific Player Analysis
    for _, row in df.iterrows():
        if player_matches_query(row['player'], prompt_lower):
            is_ass = row['player'] in assigned
            starter_txt = "Titolare confermato 2026/27" if row.get('is_starter_2627') else "Rotazione / Non ancora titolare fisso"
            return jsonify({
                "type": "player_deepdive",
                "title": f"Scheda Analitica: {row['player']} ({row['team']})",
                "engine": "Regole Tattiche Locali (Offline)",
                "player": {
                    "name": row['player'],
                    "team": row['team'],
                    "role": row['role'],
                    "role_mantra": str(row.get('role_mantra', '')),
                    "pts_exp": float(row.get('predicted_pts_p50', 0)),
                    "pts_floor": float(row.get('predicted_pts_p10', 0)),
                    "pts_ceil": float(row.get('predicted_pts_p90', 0)),
                    "fair_1000": int(row.get('prezzo_fair_1000', 1)),
                    "surplus": int(row.get('surplus_value_cr', 0)),
                    "vorp": float(row.get('vorp_points', 0)),
                    "starts": int(row.get('starts_2627', 0)),
                    "minutes": int(row.get('minutes_2627', 0)),
                    "injury_days": int(row.get('giorni_infortunio_3y', 0)),
                    "is_assigned": is_ass
                },
                "verdict": f"Valutazione Modello: Prezzo fair stimato a 1000cr: **{row.get('prezzo_fair_1000', 1)} cr**. {starter_txt} con proiezione P50 di **{row.get('predicted_pts_p50', 0):.1f} punti attesi** e VORP **+{row.get('vorp_points', 0):.1f}**."
            })

    # D. Recommendations by Role, Team, Budget, or Modificatore
    role_map = {'portier': 'P', 'difensor': 'D', 'centrocampist': 'C', 'attaccant': 'A'}
    target_role = None
    for k, v in role_map.items():
        if k in prompt_lower:
            target_role = v
            break

    team_map = {
        'como': 'COM', 'milan': 'MIL', 'juve': 'JUV', 'juventus': 'JUV',
        'inter': 'INT', 'roma': 'ROM', 'lazio': 'LAZ', 'atalanta': 'ATA',
        'napoli': 'NAP', 'bologna': 'BOL', 'fiorentina': 'FIO', 'torino': 'TOR',
        'genoa': 'GEN', 'lecce': 'LEC', 'udinese': 'UDI', 'parma': 'PAR',
        'sassuolo': 'SAS', 'monza': 'MON', 'venezia': 'VEN', 'frosinone': 'FRO',
        'cagliari': 'CAG'
    }
    target_team = None
    for k_team, v_code in team_map.items():
        if re.search(rf'\b{re.escape(k_team)}\b', prompt_lower):
            target_team = v_code
            break

    budget_match = re.search(r'(?:sotto|meno di|max|entro|budget|fino a)\s*(\d+)', prompt_lower)
    max_budget = int(budget_match.group(1)) if budget_match else None

    filtered = df.copy()
    filtered = filtered[~filtered['player'].isin(assigned.keys())]

    if target_team:
        filtered = filtered[filtered['team'] == target_team]
    if target_role:
        filtered = filtered[filtered['role'] == target_role]
    if max_budget:
        filtered = filtered[filtered['prezzo_fair_1000'] <= max_budget]

    if 'modificatore' in prompt_lower or 'difesa' in prompt_lower:
        filtered = filtered[filtered['role'] == 'D'].sort_values(['is_starter_2627', 'predicted_pts_p50'], ascending=[False, False])
    elif 'scommess' in prompt_lower or 'low cost' in prompt_lower or '1 credito' in prompt_lower:
        filtered = filtered[filtered['prezzo_fair_1000'] <= 5].sort_values(['is_starter_2627', 'predicted_pts_p50'], ascending=[False, False])
    else:
        filtered = filtered.sort_values(['is_starter_2627', 'vorp_points'], ascending=[False, False])

    top_matches = filtered.head(5)
    records = []
    for _, r in top_matches.iterrows():
        records.append({
            "name": r['player'],
            "team": r['team'],
            "role": r['role'],
            "pts_exp": float(r.get('predicted_pts_p50', 0)),
            "fair_1000": int(r.get('prezzo_fair_1000', 1)),
            "vorp": float(r.get('vorp_points', 0)),
            "starts": int(r.get('starts_2627', 0))
        })

    role_desc = {"P": "Portieri", "D": "Difensori", "C": "Centrocampisti", "A": "Attaccanti"}.get(target_role, "Calciatori")
    team_desc = f" ({target_team})" if target_team else ""
    budget_desc = f" entro {max_budget} cr" if max_budget else ""

    return jsonify({
        "type": "recommendations",
        "title": f"Migliori Opportunità Disponibili: {role_desc}{team_desc}{budget_desc}",
        "engine": "Regole Tattiche Locali (Offline)",
        "players": records,
        "verdict": "Consiglio Tattico: I profili selezionati offrono il miglior compromesso tra titolarità confermata e surplus di valore VORP."
    })


@app.route("/api/favorite", methods=["POST"])
def api_favorite():
    data = request.json or {}
    player_name = data.get("player")
    if not player_name:
        return jsonify({"error": "Specificare il calciatore"}), 400

    state = load_state()
    favs = set(state.get("favorites", []))
    if player_name in favs:
        favs.remove(player_name)
    else:
        favs.add(player_name)

    state["favorites"] = list(favs)
    save_state(state)
    return jsonify({"success": True, "favorites": state["favorites"]})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    state = get_initial_state()
    save_state(state)
    return jsonify({"success": True, "state": state})


# ──────────────────────────────────────────────────────────────────────
# FRONTEND TEMPLATE (PROFESSIONAL EXECUTIVE DARK THEME)
# ──────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Spectre - FantaMoneyball — Centro Decisionale Asta & Strategia</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #030408;
            --surface: rgba(12, 15, 25, 0.82);
            --surface-elevated: rgba(24, 28, 44, 0.88);
            --surface-solid: #080a12;
            --border: rgba(255, 45, 117, 0.18);
            --border-glow: rgba(255, 45, 117, 0.55);
            --border-focus: #ff2d75;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #ff2d75;
            --primary-accent: #f43f5e;
            --primary-glow: rgba(255, 45, 117, 0.4);
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --gold: #fbbf24;
            --purple: #a855f7;
            --role-p: #f59e0b;
            --role-d: #10b981;
            --role-c: #38bdf8;
            --role-a: #ff2d75;
        }

        html {
            font-size: 16px;
            -webkit-text-size-adjust: 100%;
            text-size-adjust: 100%;
            width: 100%;
            overflow-x: hidden;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        h1, h2, h3, h4, .brand-title, .sidebar-bot-name, .card-title, .modal-title, .pitch-title-badge, .scout-price-val {
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        body {
            background: 
                radial-gradient(circle at 12% 10%, rgba(255, 45, 117, 0.15) 0%, transparent 45%),
                radial-gradient(circle at 88% 15%, rgba(244, 63, 94, 0.12) 0%, transparent 45%),
                radial-gradient(circle at 50% 90%, rgba(168, 85, 247, 0.08) 0%, transparent 55%),
                #030408;
            background-attachment: fixed;
            color: var(--text-main);
            padding-bottom: 90px;
            line-height: 1.5;
            font-size: 1rem;
            width: 100%;
            overflow-x: hidden;
        }

        /* Layout Grid */
        .app-layout {
            display: flex;
            min-height: 100vh;
            width: 100%;
        }

        /* Sidebar */
        .app-sidebar {
            width: 280px;
            background: var(--surface);
            border-right: 1px solid var(--border);
            padding: 24px 18px;
            display: flex;
            flex-direction: column;
            gap: 18px;
            position: fixed;
            top: 0;
            bottom: 0;
            left: 0;
            z-index: 1500;
            overflow-y: auto;
            transition: transform 0.25s ease;
        }

        .sidebar-bot-card {
            background: #0b111e;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.5);
        }

        .sidebar-avatar-wrap {
            position: relative;
            width: 92px;
            height: 92px;
            border-radius: 50%;
            padding: 3px;
            background: linear-gradient(135deg, #38bdf8, #0284c7, #fbbf24);
            box-shadow: 0 0 20px rgba(56, 189, 248, 0.4);
        }

        .sidebar-avatar {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
            display: block;
            background: #111726;
        }

        .sidebar-bot-name {
            font-size: 1.15rem;
            font-weight: 800;
            color: var(--text-main);
            letter-spacing: -0.3px;
        }

        .sidebar-bot-sub {
            font-size: 0.8rem;
            color: var(--primary);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .sidebar-advice-box {
            background: rgba(56, 189, 248, 0.07);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 8px;
            padding: 12px;
            font-size: 0.85rem;
            color: var(--text-muted);
            text-align: left;
            line-height: 1.45;
        }
        .sidebar-advice-title {
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 4px;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .sidebar-nav {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .sidebar-nav-btn {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
            border-radius: 8px;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            text-align: left;
            transition: all 0.15s ease;
        }
        .sidebar-nav-btn:hover {
            background: var(--surface-elevated);
            color: var(--text-main);
        }
        .sidebar-nav-btn.active {
            background: rgba(56, 189, 248, 0.15);
            color: var(--primary);
            font-weight: 700;
            border: 1px solid rgba(56, 189, 248, 0.4);
        }

        .sidebar-profile-card {
            margin-top: auto;
            background: #0b111e;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 0.85rem;
        }

        .main-wrapper {
            flex: 1;
            margin-left: 280px;
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            width: calc(100% - 280px);
            min-width: 0;
        }

        /* Responsive Breakpoint for Mobile & Tablets */
        @media (max-width: 899px) {
            .app-sidebar {
                transform: translateX(-100%);
            }
            .app-sidebar.open {
                transform: translateX(0);
            }
            .sidebar-backdrop {
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.75);
                z-index: 1400;
                display: none;
            }
            .sidebar-backdrop.show {
                display: block;
            }
            .main-wrapper {
                margin-left: 0;
                width: 100%;
            }
        }

        @media (min-width: 900px) {
            nav.bottom-nav {
                display: none;
            }
            .mobile-sidebar-toggle {
                display: none;
            }
        }

        header {
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 12px 16px;
            position: sticky;
            top: 0;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .brand-title {
            font-size: 1.15rem;
            font-weight: 800;
            color: var(--primary);
            letter-spacing: -0.3px;
        }
        .brand-tag {
            font-size: 0.75rem;
            background: rgba(56, 189, 248, 0.15);
            color: var(--primary);
            border: 1px solid rgba(56, 189, 248, 0.35);
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 700;
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .profile-btn {
            background: var(--surface-elevated);
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 0.88rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
        }

        .admin-badge-btn {
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            border: 1px solid var(--border);
            background: #0b111e;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .admin-badge-btn.unlocked {
            background: rgba(16,185,129,0.18);
            border-color: rgba(16,185,129,0.5);
            color: var(--success);
        }

        .header-bot-pill {
            display: flex;
            align-items: center;
            gap: 8px;
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            padding: 4px 10px 4px 6px;
            border-radius: 20px;
            cursor: pointer;
        }
        .header-avatar-img {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid var(--primary);
        }

        .container {
            padding: 16px;
            max-width: 900px;
            margin: 0 auto;
            width: 100%;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* Navigation */
        nav.bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: var(--surface);
            border-top: 1px solid var(--border);
            display: flex;
            height: 68px;
            z-index: 1000;
            padding-bottom: env(safe-area-inset-bottom);
        }
        .nav-item {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.74rem;
            font-weight: 600;
            cursor: pointer;
            border: none;
            background: transparent;
            gap: 4px;
            transition: color 0.15s ease;
        }
        .nav-item.active { color: var(--primary); font-weight: 700; }
        .nav-svg { width: 22px; height: 22px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

        /* Cards & Metrics */
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            width: 100%;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }
        .card-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-main);
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }

        /* Inputs & Buttons */
        input, select, textarea {
            width: 100%;
            padding: 12px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: #0b111e;
            color: var(--text-main);
            font-size: 1rem;
            margin-bottom: 10px;
            outline: none;
        }
        input:focus, select:focus, textarea:focus { border-color: var(--border-focus); }

        .btn {
            width: 100%;
            min-height: 48px;
            padding: 12px 16px;
            border-radius: 8px;
            border: none;
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            transition: background 0.15s ease;
        }
        .btn-primary { background: linear-gradient(135deg, #ff2d75, #f43f5e); color: #ffffff; box-shadow: 0 0 16px rgba(255, 45, 117, 0.4); }
        .btn-primary:active { background: #e11d48; box-shadow: 0 0 8px rgba(255, 45, 117, 0.6); }
        .btn-secondary { background: var(--surface-elevated); color: var(--text-main); border: 1px solid var(--border); }
        .btn-danger { background: rgba(239,68,68,0.15); color: var(--danger); border: 1px solid rgba(239,68,68,0.4); }

        .price-row { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; }
        .price-input { width: 120px; text-align: center; font-size: 1.4rem; font-weight: 800; color: var(--gold); }
        .btn-step { flex: 1; min-height: 44px; padding: 10px 6px; border-radius: 8px; background: var(--surface-elevated); border: 1px solid var(--border); color: var(--text-main); font-size: 0.95rem; font-weight: 700; cursor: pointer; }

        .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 800; text-align: center; }
        .badge-P { background: rgba(245,158,11,0.18); color: var(--role-p); border: 1px solid rgba(245,158,11,0.4); }
        .badge-D { background: rgba(16,185,129,0.18); color: var(--role-d); border: 1px solid rgba(16,185,129,0.4); }
        .badge-C { background: rgba(56,189,248,0.18); color: var(--role-c); border: 1px solid rgba(56,189,248,0.4); }
        .badge-A { background: rgba(255,45,117,0.18); color: var(--role-a); border: 1px solid rgba(255,45,117,0.45); }

        .tier-badge { font-size: 0.75rem; font-weight: 700; padding: 3px 8px; border-radius: 4px; }
        .tier-1 { background: rgba(239,68,68,0.18); color: #f87171; border: 1px solid rgba(239,68,68,0.4); }
        .tier-2 { background: rgba(245,158,11,0.18); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4); }
        .tier-3 { background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid rgba(16,185,129,0.4); }

        .pills {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 6px;
            margin-bottom: 14px;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }
        .pills::-webkit-scrollbar { display: none; }
        .pill {
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 0.88rem;
            font-weight: 600;
            background: var(--surface-elevated);
            color: var(--text-muted);
            border: 1px solid var(--border);
            white-space: nowrap;
            cursor: pointer;
            flex-shrink: 0;
            transition: all 0.15s ease;
        }
        .pill.active { background: linear-gradient(135deg, #ff2d75, #f43f5e); color: #ffffff; border-color: #ff2d75; font-weight: 800; box-shadow: 0 0 14px rgba(255, 45, 117, 0.45); }

        /* ══════════════════════════════════════════════════════════════════
           SPORT-TECH SCOUTING PLAYER CARDS
           ══════════════════════════════════════════════════════════════════ */
        .player-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 14px;
            background: rgba(15, 23, 42, 0.55);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-left: 4px solid var(--border);
            border-radius: 12px;
            margin-bottom: 8px;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .player-row:hover {
            background: rgba(30, 41, 59, 0.75);
            border-color: rgba(255, 255, 255, 0.14);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
        }
        .player-row.role-P { border-left-color: var(--role-p); }
        .player-row.role-D { border-left-color: var(--role-d); }
        .player-row.role-C { border-left-color: var(--role-c); }
        .player-row.role-A { border-left-color: var(--role-a); }

        .player-info { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
        .player-name { font-weight: 700; font-size: 1.05rem; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .player-meta { font-size: 0.8rem; color: var(--text-muted); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        
        .scout-tag-starter {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            color: var(--success);
            font-size: 0.73rem;
            font-weight: 700;
            background: rgba(16, 185, 129, 0.12);
            padding: 1px 6px;
            border-radius: 4px;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .scout-vorp-badge {
            display: inline-flex;
            align-items: center;
            padding: 2px 7px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 800;
            background: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
        }

        .player-stats {
            text-align: right;
            min-width: 95px;
            flex-shrink: 0;
            padding-left: 10px;
        }
        .scout-price-box {
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.12), rgba(217, 119, 6, 0.12));
            border: 1px solid rgba(251, 191, 36, 0.35);
            border-radius: 8px;
            padding: 4px 8px;
            display: inline-block;
            box-shadow: 0 0 10px rgba(251, 191, 36, 0.08);
        }
        .player-fair {
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            color: var(--gold);
            font-size: 1.15rem;
            line-height: 1;
        }
        .player-vorp { font-size: 0.78rem; font-weight: 700; margin-top: 2px; }

        .target-icon-btn {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border);
            border-radius: 8px;
            width: 34px;
            height: 34px;
            display: inline-flex;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            color: var(--text-muted);
            margin-right: 6px;
            flex-shrink: 0;
            transition: all 0.15s ease;
        }
        .target-icon-btn:hover {
            border-color: var(--gold);
            color: var(--gold);
        }
        .target-icon-btn.active {
            background: rgba(251,191,36,0.22);
            border-color: rgba(251,191,36,0.7);
            color: var(--gold);
            box-shadow: 0 0 10px rgba(251, 191, 36, 0.3);
        }

        /* ══════════════════════════════════════════════════════════════════
           TACTICAL FANTASY STADIUM PITCH (2D VIRTUAL FIELD)
           ══════════════════════════════════════════════════════════════════ */
        .tactical-pitch-card {
            background: linear-gradient(180deg, rgba(13, 22, 38, 0.85) 0%, rgba(9, 14, 26, 0.95) 100%);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 18px;
            padding: 16px;
            margin-bottom: 18px;
            box-shadow: 0 12px 35px -8px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255,255,255,0.1);
            backdrop-filter: blur(16px);
        }
        .pitch-top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }
        .pitch-title-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 0.98rem;
            color: #38bdf8;
            letter-spacing: -0.2px;
        }
        .pitch-board {
            position: relative;
            width: 100%;
            min-height: 400px;
            background: radial-gradient(ellipse at center, #0e3b23 0%, #082617 65%, #05190f 100%);
            border-radius: 14px;
            border: 2px solid rgba(255, 255, 255, 0.16);
            box-shadow: inset 0 0 45px rgba(0, 0, 0, 0.75);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 16px 12px;
        }
        .pitch-board::before {
            content: '';
            position: absolute;
            inset: 0;
            background: repeating-linear-gradient(180deg, transparent 0, transparent 40px, rgba(255,255,255,0.018) 40px, rgba(255,255,255,0.018) 80px);
            pointer-events: none;
        }
        .pitch-board::after {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 90px;
            height: 90px;
            border: 1.5px solid rgba(255, 255, 255, 0.14);
            border-radius: 50%;
            pointer-events: none;
        }
        .pitch-midline {
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 1.5px;
            background: rgba(255, 255, 255, 0.14);
            pointer-events: none;
        }
        .pitch-penalty-top {
            position: absolute;
            top: 0;
            left: 50%;
            transform: translateX(-50%);
            width: 130px;
            height: 52px;
            border: 1.5px solid rgba(255, 255, 255, 0.14);
            border-top: none;
            border-radius: 0 0 8px 8px;
            pointer-events: none;
        }
        .pitch-penalty-bottom {
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%);
            width: 130px;
            height: 52px;
            border: 1.5px solid rgba(255, 255, 255, 0.14);
            border-bottom: none;
            border-radius: 8px 8px 0 0;
            pointer-events: none;
        }
        .pitch-row {
            display: flex;
            justify-content: space-around;
            align-items: center;
            position: relative;
            z-index: 2;
            width: 100%;
            min-height: 72px;
            gap: 4px;
            flex-wrap: wrap;
        }
        .pitch-node {
            display: flex;
            flex-direction: column;
            align-items: center;
            cursor: pointer;
            transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
            max-width: 76px;
            text-align: center;
            padding: 4px;
        }
        .pitch-node:hover {
            transform: scale(1.15);
            z-index: 5;
        }
        .pitch-jersey {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Outfit', sans-serif;
            font-weight: 800;
            font-size: 0.85rem;
            color: #ffffff;
            box-shadow: 0 4px 14px rgba(0,0,0,0.6);
            border: 2px solid rgba(255,255,255,0.35);
            margin-bottom: 3px;
        }
        .pitch-jersey.role-P { background: linear-gradient(135deg, #f59e0b, #d97706); box-shadow: 0 0 14px rgba(245, 158, 11, 0.45); }
        .pitch-jersey.role-D { background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 0 14px rgba(16, 185, 129, 0.45); }
        .pitch-jersey.role-C { background: linear-gradient(135deg, #38bdf8, #0284c7); box-shadow: 0 0 14px rgba(56, 189, 248, 0.45); }
        .pitch-jersey.role-A { background: linear-gradient(135deg, #f43f5e, #e11d48); box-shadow: 0 0 14px rgba(244, 63, 94, 0.45); }

        .pitch-node-name {
            font-size: 0.7rem;
            font-weight: 700;
            color: #ffffff;
            background: rgba(0, 0, 0, 0.78);
            padding: 2px 6px;
            border-radius: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 72px;
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255,255,255,0.1);
        }
        .pitch-node-price {
            font-size: 0.65rem;
            font-weight: 800;
            color: #fbbf24;
            margin-top: 1px;
            text-shadow: 0 1px 2px rgba(0,0,0,0.8);
        }
        .pitch-node-empty .pitch-jersey {
            background: rgba(255, 255, 255, 0.05);
            border: 1.5px dashed rgba(255, 255, 255, 0.28);
            color: rgba(255, 255, 255, 0.35);
            box-shadow: none;
        }
        .pitch-node-empty .pitch-node-name {
            background: rgba(0,0,0,0.4);
            color: rgba(255,255,255,0.4);
            border: none;
        }

        /* Financial HUD Progress Bar */
        .hud-squad-bar {
            width: 100%;
            height: 8px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0 6px 0;
            position: relative;
        }
        .hud-squad-progress {
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #10b981, #fbbf24);
            border-radius: 4px;
            transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.5);
        }

        .suggestions { background: var(--surface-elevated); border: 1px solid var(--border); border-radius: 8px; max-height: 240px; overflow-y: auto; margin-top: -6px; margin-bottom: 12px; }
        .suggestion-item { padding: 12px 14px; border-bottom: 1px solid rgba(36,49,76,0.6); cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
        .suggestion-item:active { background: #24314c; }

        /* Dashboard Overview */
        .dept-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
        @media (max-width: 599px) {
            .dept-grid { grid-template-columns: repeat(2, 1fr) !important; gap: 8px !important; }
            .container { padding: 12px !important; }
            .price-input { width: 95px !important; font-size: 1.25rem !important; }
        }
        .dept-card { background: #0b111e; border: 1px solid var(--border); border-radius: 8px; padding: 12px 8px; text-align: center; }
        .dept-label { font-size: 0.78rem; font-weight: 800; margin-bottom: 4px; text-transform: uppercase; }
        .dept-spent { font-size: 1.2rem; font-weight: 800; color: var(--gold); }
        .dept-count { font-size: 0.78rem; color: var(--text-muted); }

        .slot-section { margin-bottom: 16px; }
        .slot-title { font-size: 0.9rem; font-weight: 700; margin-bottom: 8px; display: flex; justify-content: space-between; color: var(--text-muted); border-bottom: 1px solid var(--border); padding-bottom: 6px; text-transform: uppercase; }
        .slot-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: #0b111e; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; font-size: 0.92rem; }
        .slot-row.empty { background: transparent; border: 1px dashed rgba(36,49,76,0.8); color: #64748b; font-style: italic; }
        .slot-num { font-size: 0.8rem; color: var(--text-muted); width: 26px; font-weight: 700; }
        .slot-player { font-weight: 600; display: flex; align-items: center; gap: 8px; min-width: 0; }
        .slot-price { font-weight: 800; color: var(--gold); font-size: 0.98rem; white-space: nowrap; }

        /* Modal Overlay */
        .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 2000; display: none; justify-content: center; align-items: center; padding: 16px; }
        .modal-box { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; width: 100%; max-width: 520px; padding: 20px; max-height: 90vh; overflow-y: auto; }
        .modal-title { font-size: 1.15rem; font-weight: 700; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }

        /* Strategy Planner Cards & Cluster Explorer */
        .plan-step-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            margin-bottom: 12px;
            transition: all 0.15s ease;
        }
        .plan-step-card.active-target {
            border: 2px solid var(--primary);
            background: rgba(56,189,248,0.05);
        }
        .plan-step-card.completed {
            border-color: rgba(16,185,129,0.4);
        }
        .plan-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
            cursor: pointer;
            user-select: none;
        }
        .plan-slot-title { font-weight: 700; font-size: 0.96rem; }
        .plan-budget-badge { font-size: 0.82rem; font-weight: 700; padding: 4px 10px; border-radius: 6px; background: var(--surface-elevated); color: var(--gold); border: 1px solid var(--border); white-space: nowrap; }
        .candidate-mini-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            background: #0b111e;
            border-radius: 8px;
            margin-top: 6px;
            font-size: 0.9rem;
            cursor: pointer;
        }
        .candidate-mini-row:active { background: #182238; }

        /* Overview Table */
        .table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; margin-bottom: 12px; }
        .overview-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        .overview-table th, .overview-table td { padding: 10px 8px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; }
        .overview-table th:first-child, .overview-table td:first-child { text-align: left; }
        .overview-table th { color: var(--text-muted); font-weight: 700; background: var(--surface-elevated); }
        .overview-table tr:hover { background: rgba(56,189,248,0.04); }

        /* AI Chat / Query Box */
        .ai-query-card {
            background: linear-gradient(180deg, rgba(56,189,248,0.1) 0%, rgba(17,23,38,1) 100%);
            border: 1px solid rgba(56,189,248,0.35);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .ai-pill {
            padding: 8px 14px;
            border-radius: 20px;
            background: rgba(56,189,248,0.12);
            border: 1px solid rgba(56,189,248,0.3);
            color: var(--primary);
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            flex-shrink: 0;
        }
        .ai-pill:hover {
            background: var(--primary);
            color: #090d16;
        }

        /* Conversational Chat UI */
        .chat-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-height: 280px;
            max-height: 540px;
            overflow-y: auto;
            padding: 8px 2px;
            margin-bottom: 12px;
            scroll-behavior: smooth;
        }
        .chat-msg {
            display: flex;
            gap: 10px;
            max-width: 92%;
            animation: fadeInMsg 0.2s ease-in-out;
        }
        @keyframes fadeInMsg {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .chat-msg.user {
            align-self: flex-end;
            flex-direction: row-reverse;
        }
        .chat-msg.ai {
            align-self: flex-start;
            width: 100%;
        }
        .chat-msg-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            object-fit: cover;
            border: 1.5px solid var(--primary);
            flex-shrink: 0;
            margin-top: 2px;
        }
        .chat-bubble {
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 0.95rem;
            line-height: 1.5;
            word-break: break-word;
        }
        .chat-msg.user .chat-bubble {
            background: #0284c7;
            color: #ffffff;
            border-bottom-right-radius: 2px;
        }
        .chat-msg.ai .chat-bubble {
            background: var(--surface-elevated);
            border: 1px solid var(--border);
            color: var(--text-main);
            border-bottom-left-radius: 2px;
            width: 100%;
        }
        .chat-input-row {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        /* Market Inflation Badge */
        .market-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid var(--border);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.76rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
            user-select: none;
        }
        .market-pill:hover {
            border-color: var(--primary);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }
        .dot-green { background: var(--success); box-shadow: 0 0 6px var(--success); }
        .dot-yellow { background: var(--warning); box-shadow: 0 0 6px var(--warning); }
        .dot-red { background: var(--danger); box-shadow: 0 0 6px var(--danger); }
        .dot-blue { background: var(--primary); box-shadow: 0 0 6px var(--primary); }

        /* Toast Notifications */
        .toast-container {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
            max-width: 380px;
        }
        .toast {
            background: #111726;
            color: var(--text-main);
            border: 1px solid var(--border);
            padding: 12px 18px;
            border-radius: 10px;
            font-size: 0.88rem;
            font-weight: 600;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            display: flex;
            align-items: center;
            gap: 10px;
            pointer-events: auto;
            animation: slideInToast 0.25s ease-out;
            transition: opacity 0.3s ease, transform 0.3s ease;
        }
        .toast.toast-success { border-color: var(--success); }
        .toast.toast-danger { border-color: var(--danger); }
        .toast.toast-warning { border-color: var(--warning); }
        .toast.toast-info { border-color: var(--primary); }
        @keyframes slideInToast {
            from { transform: translateX(40px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        /* ══════════════════════════════════════════════════════════════════
           RESPONSIVE VIEWPORT ISOLATION (PC DESKTOP VS MOBILE)
        ══════════════════════════════════════════════════════════════════ */
        @media (min-width: 900px) {
            nav.bottom-nav {
                display: none !important;
            }
            body {
                padding-bottom: 28px !important;
            }
            .mobile-sidebar-toggle {
                display: none !important;
            }
            .header-bot-pill {
                display: none !important;
            }
            .desktop-brand-title {
                display: inline-flex !important;
                align-items: center;
                gap: 8px;
            }
            .container {
                max-width: 1080px;
                margin: 0 auto;
                padding: 24px 28px;
            }
        }

        @media (max-width: 899px) {
            /* Smooth Airy Bottom Navigation */
            nav.bottom-nav {
                display: flex !important;
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                height: 58px;
                background: rgba(4, 6, 12, 0.94) !important;
                backdrop-filter: blur(20px) !important;
                -webkit-backdrop-filter: blur(20px) !important;
                border-top: 1px solid rgba(255, 45, 117, 0.22) !important;
                box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.7) !important;
                z-index: 1000;
                padding-bottom: max(4px, env(safe-area-inset-bottom, 6px)) !important;
                padding-top: 3px !important;
            }
            .nav-item {
                flex: 1;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                color: #94a3b8;
                font-size: 0.68rem !important;
                font-weight: 600;
                cursor: pointer;
                border: none;
                background: transparent;
                gap: 2px !important;
                padding: 4px 1px !important;
                border-radius: 8px;
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
                transition: all 0.15s ease;
            }
            .nav-item:active {
                transform: scale(0.92);
            }
            .nav-item.active {
                color: #ff2d75 !important;
                font-weight: 800 !important;
                background: rgba(255, 45, 117, 0.09) !important;
            }
            .nav-item.active .nav-svg {
                stroke: #ff2d75 !important;
                filter: drop-shadow(0 0 6px rgba(255, 45, 117, 0.75)) !important;
            }
            .nav-svg {
                width: 19px !important;
                height: 19px !important;
            }

            body {
                padding-bottom: calc(68px + env(safe-area-inset-bottom, 12px)) !important;
            }
            .container {
                padding: 10px 8px !important;
            }

            /* De-densified Cards & Spacing */
            .card {
                padding: 12px 10px !important;
                margin-bottom: 10px !important;
                border-radius: 10px !important;
            }
            .card-header {
                margin-bottom: 8px !important;
                padding-bottom: 6px !important;
            }
            .card-title {
                font-size: 0.88rem !important;
            }

            /* Compact Ergonomic Pills */
            .pills {
                gap: 6px !important;
                margin-bottom: 10px !important;
                padding-bottom: 4px !important;
            }
            .pill {
                padding: 6px 12px !important;
                font-size: 0.78rem !important;
                font-weight: 700 !important;
                border-radius: 18px !important;
            }

            /* Lightweight Player Rows */
            .player-row {
                padding: 9px 10px !important;
                margin-bottom: 6px !important;
                border-radius: 9px !important;
                gap: 6px !important;
            }
            .player-name {
                font-size: 0.92rem !important;
                gap: 5px !important;
            }
            .player-meta {
                font-size: 0.72rem !important;
                gap: 4px !important;
            }
            .scout-price-box {
                padding: 3px 7px !important;
                border-radius: 6px !important;
            }
            .player-fair {
                font-size: 0.92rem !important;
            }

            /* Compact 2D Pitch */
            .pitch-board {
                min-height: 280px !important;
                max-height: 330px !important;
                padding: 10px 6px !important;
                border-radius: 10px !important;
            }
            .pitch-node {
                min-width: 46px !important;
            }
            .pitch-jersey {
                width: 28px !important;
                height: 28px !important;
                font-size: 0.72rem !important;
            }
            .pitch-node-name {
                font-size: 0.65rem !important;
                max-width: 56px !important;
            }
            .pitch-node-price {
                font-size: 0.65rem !important;
            }

            /* Department Grid */
            .dept-grid {
                gap: 6px !important;
            }
            .dept-card {
                padding: 8px 4px !important;
                border-radius: 6px !important;
            }
            .dept-label {
                font-size: 0.65rem !important;
            }
            .dept-spent {
                font-size: 0.95rem !important;
            }
            .dept-count {
                font-size: 0.70rem !important;
            }

            .mobile-sidebar-toggle {
                display: flex !important;
            }
            .header-bot-pill {
                display: inline-flex !important;
            }
            .desktop-brand-title {
                display: none !important;
            }
            .hide-mobile {
                display: none !important;
            }
            .market-pill {
                padding: 3px 8px;
                font-size: 0.7rem;
            }
        }
    </style>
</head>
<body>

    <div class="sidebar-backdrop" id="sidebarBackdrop" onclick="toggleMobileSidebar()"></div>

    <div class="app-layout">

        <!-- LATERAL SIDEBAR (TACTICAL ASSISTANT & NAVIGATION) -->
        <aside class="app-sidebar" id="appSidebar">
            <div class="sidebar-bot-card">
                <div class="sidebar-avatar-wrap">
                    {% if bot_avatar_image %}
                    <img src="{{ bot_avatar_image }}" class="sidebar-avatar" style="width:64px; height:64px; border-radius:50%; object-fit:cover; display:block; margin:0 auto; border:2.5px solid var(--primary); box-shadow:0 0 20px rgba(255,45,117,0.65);" alt="{{ bot_name }}">
                    {% else %}
                    <div class="sidebar-avatar" style="width:54px; height:54px; border-radius:50%; background:linear-gradient(135deg, #ff2d75, #a855f7); display:flex; align-items:center; justify-content:center; margin:0 auto; border:2px solid var(--primary); box-shadow: 0 0 16px rgba(255,45,117,0.5); font-family:'Outfit',sans-serif; font-size:1.25rem; font-weight:800; color:#ffffff;">
                        {{ bot_avatar_text }}
                    </div>
                    {% endif %}
                </div>
                <div>
                    <div class="sidebar-bot-name">{{ bot_name }}</div>
                    <div class="sidebar-bot-sub" style="color:var(--primary); font-style:italic; font-weight:600;">"{{ bot_subtitle }}"</div>
                </div>
                <div class="sidebar-advice-box">
                    <div class="sidebar-advice-title">Consiglio Live</div>
                    <div id="sidebarLiveAdvice">Monitora la scarsità dei ruoli e rispetta i tetti Stop-Loss prefissati.</div>
                </div>
            </div>

            <div class="sidebar-nav">
                <!-- Gated Admin Tab -->
                <button class="sidebar-nav-btn" id="sideNav-draft" onclick="switchTab('draft')" style="display:none;">
                    <svg class="nav-svg" viewBox="0 0 24 24"><path d="m14 7 3 3m-9.5 7.5 7-7m-5-5 3.5-3.5a2.121 2.121 0 0 1 3 3L12.5 5.5m-5 5L2 16l6 6 5.5-5.5"></path></svg>
                    <span>Asta Live (Battitore)</span>
                </button>

                <button class="sidebar-nav-btn active" id="sideNav-targets" onclick="switchTab('targets')">
                    <svg class="nav-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>
                    <span>I Miei Target</span>
                </button>
                <button class="sidebar-nav-btn" id="sideNav-ai" onclick="switchTab('ai')">
                    <svg class="nav-svg" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                    <span>Chiedi a {{ bot_name }}</span>
                </button>
                <button class="sidebar-nav-btn" id="sideNav-strategy" onclick="switchTab('strategy')">
                    <svg class="nav-svg" viewBox="0 0 24 24"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>
                    <span>Scala Slot</span>
                </button>
                <button class="sidebar-nav-btn" id="sideNav-rosters" onclick="switchTab('rosters')">
                    <svg class="nav-svg" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    <span>Rose & Finanze</span>
                </button>
                <button class="sidebar-nav-btn" id="sideNav-listone" onclick="switchTab('listone')">
                    <svg class="nav-svg" viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
                    <span>Listone Analytics</span>
                </button>
            </div>

            <div class="sidebar-profile-card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <span style="color:var(--text-muted); font-size:0.7rem; font-weight:700;">MANAGER ATTIVO</span>
                    <button style="background:transparent; border:none; color:var(--primary); font-size:0.72rem; cursor:pointer; font-weight:700;" onclick="openProfileModal()">Cambia</button>
                </div>
                <div id="sideProfileName" style="font-weight:800; font-size:0.95rem; color:var(--text-main);">Io</div>
                <div id="sideProfileBudget" style="color:var(--gold); font-weight:700; font-size:0.85rem; margin-top:2px;">1000 cr residui</div>
            </div>

            <div style="margin-top:auto; padding:12px 10px; text-align:center;">
                <a href="https://buymeacoffee.com/blueskies360" target="_blank" rel="noopener noreferrer" style="display:inline-flex; align-items:center; justify-content:center; gap:6px; background:#fbbf24; color:#090d16; font-size:0.75rem; font-weight:800; padding:6px 14px; border-radius:20px; text-decoration:none; box-shadow:0 2px 8px rgba(251,191,36,0.3); width:100%;">
                    <span>☕ Offri un Caffè</span>
                </a>
            </div>
        </aside>

        <!-- MAIN CONTENT WRAPPER -->
        <div class="main-wrapper">

            <header>
                <div class="brand">
                    <button class="profile-btn mobile-sidebar-toggle" onclick="toggleMobileSidebar()" style="padding:4px 8px; margin-right:4px;">
                        <svg class="nav-svg" style="width:18px; height:18px;" viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
                    </button>
                    <div class="header-bot-pill" onclick="toggleMobileSidebar()" title="Menu Tattico">
                        {% if bot_avatar_image %}
                        <img src="{{ bot_avatar_image }}" style="width:28px; height:28px; border-radius:50%; object-fit:cover; border:1.5px solid var(--primary); margin-right:6px; box-shadow:0 0 10px rgba(255,45,117,0.55);" alt="{{ bot_name }}">
                        {% else %}
                        <div class="header-avatar-img" style="width:26px; height:26px; border-radius:50%; background:linear-gradient(135deg, #ff2d75, #a855f7); display:flex; align-items:center; justify-content:center; border:1px solid var(--primary); margin-right:4px; font-family:'Outfit',sans-serif; font-size:0.75rem; font-weight:800; color:#fff;">
                            {{ bot_avatar_text }}
                        </div>
                        {% endif %}
                        <span class="header-bot-pill-name">{{ bot_name }}</span>
                        <span class="header-bot-pill-badge">{{ bot_badge }}</span>
                    </div>

                    <div class="desktop-brand-title" style="display:none; align-items:center; gap:8px;">
                        <span style="font-family:'Outfit',sans-serif; font-weight:800; font-size:1.15rem; color:var(--text-main); letter-spacing:-0.3px;">⚡ {{ bot_name }}</span>
                        <span class="brand-tag" style="font-size:0.7rem; padding:2px 7px; background:rgba(255,45,117,0.15); border:1px solid rgba(255,45,117,0.35); color:var(--primary); font-weight:800; border-radius:4px;">{{ bot_badge }}</span>
                    </div>

                    <!-- Dynamic Market Inflation Badge -->
                    <div id="headerMarketBadge" class="market-pill" onclick="showInflationInfoModal()" title="Clicca per i dettagli dell'inflazione">
                        <span id="marketBadgeDot" class="status-dot dot-blue"></span>
                        <span id="marketBadgeText">Mercato 1.00x</span>
                    </div>
                </div>

                <div class="header-actions">
                    <button id="btnLeagueSettings" class="profile-btn" onclick="openLeagueSettingsModal()" title="Configura Budget, Slot e Squadre">
                        <span style="font-size:0.9rem;">⚙️</span>
                        <span class="hide-mobile">Lega</span>
                    </button>

                    <button id="adminUnlockBtn" class="admin-badge-btn" onclick="openAdminModal()">
                        <svg class="nav-svg" style="width:13px; height:13px;" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                        <span id="adminBtnText">Battitore</span>
                    </button>

                    <button class="profile-btn" onclick="openProfileModal()">
                        <svg class="nav-svg" style="width:14px; height:14px;" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                        <span id="headerProfileName">Io</span>
                    </button>
                </div>
            </header>

            <div class="container">

        <!-- TAB 1: BATTITORE LIVE (GATED ADMIN) -->
        <div id="tab-draft" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Chiamata & Aggiudicazione Live</div>
                    <div style="font-size:0.75rem; color:var(--text-muted);">Assegnati: <span id="draftedCount" style="color:var(--success); font-weight:700;">0</span>/290</div>
                </div>

                <input type="text" id="playerSearch" placeholder="Cerca calciatore per nome o squadra..." autocomplete="off">
                <div id="suggestionsBox" class="suggestions" style="display:none;"></div>

                <div id="selectedPlayerCard" style="display:none; margin-bottom: 12px; padding: 12px; background: #0b111e; border: 1px solid var(--border); border-radius: 8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <span id="selRole" class="badge"></span>
                            <b id="selName" style="font-size: 1.05rem; margin-left: 6px;"></b>
                            <span id="selTeam" style="font-size: 0.8rem; color: var(--text-muted);"></span>
                        </div>
                        <div style="text-align:right;">
                            <div id="selFair" style="font-weight:800; color:var(--gold); font-size:1rem;"></div>
                            <div id="selSurplus" style="font-size:0.75rem; font-weight:600;"></div>
                        </div>
                    </div>
                </div>

                <label style="font-size: 0.78rem; color: var(--text-muted); display: block; margin-bottom: 4px; font-weight:600;">Squadra Acquirente:</label>
                <select id="teamSelect"></select>

                <label style="font-size: 0.78rem; color: var(--text-muted); display: block; margin-bottom: 4px; font-weight:600;">Prezzo Finale di Aggiudicazione (Crediti):</label>
                <div class="price-row">
                    <button class="btn-step" onclick="changePrice(-10)">-10</button>
                    <button class="btn-step" onclick="changePrice(-1)">-1</button>
                    <input type="number" id="bidPrice" class="price-input" value="1" min="1">
                    <button class="btn-step" onclick="changePrice(+1)">+1</button>
                    <button class="btn-step" onclick="changePrice(+5)">+5</button>
                    <button class="btn-step" onclick="changePrice(+10)">+10</button>
                </div>

                <button class="btn btn-primary" onclick="submitAssignment()">REGISTRA ACQUISTO</button>
            </div>

            <div class="card">
                <div class="card-header">
                    <div class="card-title">Storico Chiamate Recenti</div>
                    <button class="btn-danger" style="width:auto; padding: 4px 10px; font-size: 0.75rem; border-radius: 6px; font-weight:700;" onclick="undoLast()">Annulla Ultima</button>
                </div>
                <div id="recentList" style="font-size: 0.85rem; color: var(--text-muted);">Nessuna chiamata registrata.</div>
            </div>
        </div>

        <!-- TAB 2: I MIEI TARGET & SIMULATORE STRATEGIA (DEFAULT LANDING) -->
        <div id="tab-targets" class="tab-content active">
            <div class="card" style="border-left: 4px solid var(--gold);">
                <div class="card-header">
                    <div class="card-title">Simulatore Impegno Finanziario</div>
                    <span id="targetCommitmentBadge" style="font-size:0.85rem; font-weight:800; color:var(--gold);"></span>
                </div>
                <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:8px; text-align:center; margin-top:8px;">
                    <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                        <div style="font-size:0.68rem; color:var(--text-muted); font-weight:700;">TOP TARGET (1ª FASCIA)</div>
                        <div id="commitTier1" style="font-size:1.05rem; font-weight:800; color:#f87171;">0 cr</div>
                    </div>
                    <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                        <div style="font-size:0.68rem; color:var(--text-muted); font-weight:700;">ALTERNATIVE (2ª FASCIA)</div>
                        <div id="commitTier2" style="font-size:1.05rem; font-weight:800; color:#fbbf24;">0 cr</div>
                    </div>
                    <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                        <div style="font-size:0.68rem; color:var(--text-muted); font-weight:700;">TARGET LIBERI</div>
                        <div id="targetAvailableCount" style="font-size:1.05rem; font-weight:800; color:var(--primary);">0</div>
                    </div>
                </div>
            </div>

            <!-- Target Roster Slots Coverage -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Copertura Reparti nei Target</div>
                    <button class="btn-secondary" style="width:auto; padding:4px 10px; font-size:0.75rem;" onclick="exportTargetsJSON()">Esporta Wishlist</button>
                </div>
                <div class="dept-grid">
                    <div class="dept-card">
                        <div class="dept-label" style="color:var(--role-p);">PORTIERI</div>
                        <div class="dept-spent" id="targetCoverageP">0/4</div>
                        <div class="dept-count" id="targetSpentP">0 cr max</div>
                    </div>
                    <div class="dept-card">
                        <div class="dept-label" style="color:var(--role-d);">DIFENSORI</div>
                        <div class="dept-spent" id="targetCoverageD">0/9</div>
                        <div class="dept-count" id="targetSpentD">0 cr max</div>
                    </div>
                    <div class="dept-card">
                        <div class="dept-label" style="color:var(--role-c);">CENTROCAMPISTI</div>
                        <div class="dept-spent" id="targetCoverageC">0/9</div>
                        <div class="dept-count" id="targetSpentC">0 cr max</div>
                    </div>
                    <div class="dept-card">
                        <div class="dept-label" style="color:var(--role-a);">ATTACCANTI</div>
                        <div class="dept-spent" id="targetCoverageA">0/7</div>
                        <div class="dept-count" id="targetSpentA">0 cr max</div>
                    </div>
                </div>
            </div>

            <!-- Targets Filter & List -->
            <div class="pills" id="targetRolePills">
                <div class="pill active" onclick="setTargetRoleFilter('ALL')">Tutti i Ruoli</div>
                <div class="pill" onclick="setTargetRoleFilter('P')">Portieri</div>
                <div class="pill" onclick="setTargetRoleFilter('D')">Difensori</div>
                <div class="pill" onclick="setTargetRoleFilter('C')">Centrocampisti</div>
                <div class="pill" onclick="setTargetRoleFilter('A')">Attaccanti</div>
            </div>

            <div id="targetsListContainer"></div>
        </div>

        <!-- TAB 3: CHIEDI AL TACTICAL CHATBOT -->
        <div id="tab-ai" class="tab-content">
            <div class="card" style="border-top:3px solid var(--primary); padding:16px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:10px;">
                    <div style="display:flex; align-items:center; gap:12px;">
                        {% if bot_avatar_image %}
                        <img src="{{ bot_avatar_image }}" style="width:42px; height:42px; border-radius:50%; object-fit:cover; border:2px solid var(--primary); box-shadow:0 0 14px rgba(255,45,117,0.55);" alt="{{ bot_name }}">
                        {% else %}
                        <div style="width:38px; height:38px; border-radius:50%; background:linear-gradient(135deg, #ff2d75, #a855f7); display:flex; align-items:center; justify-content:center; border:2px solid var(--primary); box-shadow:0 0 12px rgba(255,45,117,0.45); font-family:'Outfit',sans-serif; font-size:1rem; font-weight:800; color:#fff;">
                            {{ bot_avatar_text }}
                        </div>
                        {% endif %}
                        <div>
                            <div style="font-weight:800; font-size:1.15rem; color:var(--text-main); font-family:'Outfit',sans-serif;">{{ bot_name }} Chatbot</div>
                            <div style="font-size:0.75rem; color:var(--primary); font-weight:600; font-style:italic;">"{{ bot_subtitle }}"</div>
                        </div>
                    </div>
                    <button class="btn-secondary" onclick="clearAIChat()" style="width:auto; padding:6px 12px; font-size:0.78rem; font-weight:700;">
                        Pulisci Chat
                    </button>
                </div>

                <!-- AI Engine Diagnostic Bar -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; background:rgba(15,23,42,0.65); padding:6px 10px; border-radius:8px; border:1px solid var(--border);">
                    <div style="display:flex; align-items:center; gap:6px; min-width:0; overflow:hidden;">
                        <span id="aiEngineStatusDot" class="status-dot dot-yellow" style="flex-shrink:0;"></span>
                        <span style="font-size:0.75rem; color:var(--text-muted); flex-shrink:0;">Motore:</span>
                        <span id="aiActiveEngineLabel" style="font-size:0.78rem; font-weight:800; color:var(--primary); white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">Verifica in corso...</span>
                    </div>
                    <button class="btn-secondary" onclick="openAIDiagnosticsModal()" style="width:auto; padding:3px 8px; font-size:0.70rem; font-weight:700; flex-shrink:0; margin-left:6px;">
                        🔍 Diagnostica
                    </button>
                </div>

                <!-- Chat Quick Chips -->
                <div class="pills" style="margin-bottom:10px;">
                    <div class="ai-pill" onclick="setAIQuery('Analizza la mia squadra e dimmi cosa manca')">Diagnosi Rosa</div>
                    <div class="ai-pill" onclick="setAIQuery('Malen vs Lautaro Martinez')">Malen vs Lautaro</div>
                    <div class="ai-pill" onclick="setAIQuery('Migliori centrocampisti sotto 35 crediti')">Centrocampisti < 35cr</div>
                    <div class="ai-pill" onclick="setAIQuery('Top difensori per modificatore')">Modificatore Difesa</div>
                    <div class="ai-pill" onclick="setAIQuery('Scommesse attaccanti a 1 credito')">Scommesse a 1cr</div>
                    <div class="ai-pill" onclick="setAIQuery('Scheda Dimarco')">Analizza Dimarco</div>
                </div>

                <!-- Conversational Message Stream -->
                <div id="chatMessagesStream" class="chat-container">
                    <div class="chat-msg ai">
                        {% if bot_avatar_image %}
                        <img src="{{ bot_avatar_image }}" style="width:36px; height:36px; border-radius:50%; object-fit:cover; flex-shrink:0; border:1.5px solid var(--primary); box-shadow:0 0 10px rgba(255,45,117,0.55);" alt="{{ bot_name }}">
                        {% else %}
                        <div class="chat-msg-avatar" style="width:34px; height:34px; border-radius:50%; background:linear-gradient(135deg, #ff2d75, #a855f7); display:flex; align-items:center; justify-content:center; flex-shrink:0; border:1.5px solid var(--primary); font-family:'Outfit',sans-serif; font-size:0.85rem; font-weight:800; color:#fff;">
                            {{ bot_avatar_text }}
                        </div>
                        {% endif %}
                        <div class="chat-bubble">
                            <b>{{ bot_greeting }}</b>
                        </div>
                    </div>
                </div>

                <!-- Input Row -->
                <div class="chat-input-row">
                    <input type="text" id="aiInputPrompt" placeholder="Fai una domanda (es. 'Chi prendo tra Lookman e Thuram?')..." style="margin-bottom:0; flex:1;" onkeypress="if(event.key==='Enter') submitAIQuery()">
                    <button class="btn btn-primary" id="btnSubmitAI" style="width:auto; min-height:46px; padding:0 18px; font-weight:700;" onclick="submitAIQuery()">
                        Invia
                    </button>
                </div>
            </div>
        </div>

        <!-- TAB 4: STRATEGIA & SCALA SLOT -->
        <div id="tab-strategy" class="tab-content">
            <!-- Tactical Preset Selector -->
            <div class="card" style="border-left: 4px solid var(--primary);">
                <div class="card-header">
                    <div class="card-title">Impostazione Tattica & Filosofia d'Asta</div>
                    <span id="strategyRemainingBadge" style="font-size:0.85rem; color:var(--gold); font-weight:800;"></span>
                </div>
                <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:10px;">
                    Seleziona la tattica da seguire. I tetti di spesa (Stop-Loss) e i calciatori consigliati si adatteranno dinamicamente.
                </div>
                <div class="pills" id="tacticPresetPills" style="margin-bottom:12px;"></div>

                <div id="tacticOverviewCard" style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <b id="tacticTitle" style="color:var(--text-main); font-size:0.92rem;"></b>
                        <span id="tacticBadge" class="brand-tag"></span>
                    </div>
                    <div id="tacticDesc" style="font-size:0.78rem; color:var(--text-muted); margin-bottom:10px; line-height:1.4;"></div>
                    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:6px; text-align:center;">
                        <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); padding:6px; border-radius:6px;">
                            <div style="font-size:0.65rem; color:var(--role-p); font-weight:800;">POR</div>
                            <div id="splitPOR" style="font-size:0.78rem; font-weight:800; color:var(--gold);">-</div>
                        </div>
                        <div style="background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.3); padding:6px; border-radius:6px;">
                            <div style="font-size:0.65rem; color:var(--role-d); font-weight:800;">DIF</div>
                            <div id="splitDIF" style="font-size:0.78rem; font-weight:800; color:var(--gold);">-</div>
                        </div>
                        <div style="background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.3); padding:6px; border-radius:6px;">
                            <div style="font-size:0.65rem; color:var(--role-c); font-weight:800;">CEN</div>
                            <div id="splitCEN" style="font-size:0.78rem; font-weight:800; color:var(--gold);">-</div>
                        </div>
                        <div style="background:rgba(244,63,94,0.1); border:1px solid rgba(244,63,94,0.3); padding:6px; border-radius:6px;">
                            <div style="font-size:0.65rem; color:var(--role-a); font-weight:800;">ATT</div>
                            <div id="splitATT" style="font-size:0.78rem; font-weight:800; color:var(--gold);">-</div>
                        </div>
                    </div>
                    <button id="btnCustomConfig" class="btn-secondary" style="margin-top:10px; padding:7px 12px; font-size:0.78rem; font-weight:700; width:100%; display:none;" onclick="openCustomConfigModal()">⚙️ Configura Budget & Fasce Personalizzate</button>
                </div>
            </div>

            <!-- Role Selector for Slots -->
            <div class="pills" id="stratRolePills">
                <div class="pill active" onclick="setStratRole('A')">Attacco (7 Slot)</div>
                <div class="pill" onclick="setStratRole('C')">Centrocampo (9 Slot)</div>
                <div class="pill" onclick="setStratRole('D')">Difesa (9 Slot)</div>
                <div class="pill" onclick="setStratRole('P')">Porta (4 Slot)</div>
            </div>

            <div id="strategySlotsContainer"></div>
        </div>

        <!-- TAB 5: TABELLONE ROSE & FINANZE -->
        <div id="tab-rosters" class="tab-content">
            <div class="pills" id="teamFilterPills"></div>

            <div id="singleTeamView">
                <div class="card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div>
                            <h2 id="rosterTeamName" style="font-size:1.1rem; color:var(--primary); font-weight:800;">Io</h2>
                            <div style="font-size:0.75rem; color:var(--text-muted);" id="rosterSlotsProgress">0/29 Slot occupati</div>
                        </div>
                        <div style="text-align:right;">
                            <div id="rosterRemaining" style="font-size:1.3rem; font-weight:800; color:var(--gold);">1000 cr</div>
                            <div id="rosterMaxBid" style="font-size:0.75rem; color:var(--danger); font-weight:700;">Max Bid: 972 cr</div>
                        </div>
                    </div>

                    <!-- Financial HUD Progress Bar -->
                    <div class="hud-squad-bar" title="Avanzamento Spesa Budget">
                        <div class="hud-squad-progress" id="hudSquadProgress" style="width: 0%;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.74rem; color:var(--text-muted); margin-bottom:14px;">
                        <span>Spesi: <b id="hudSpentTotal" style="color:var(--text-main);">0 cr</b> (<span id="hudSpentPercent">0%</span>)</span>
                        <span>VORP Cumulato: <b id="hudTotalVorp" style="color:var(--primary);">+0.0</b></span>
                    </div>

                    <!-- Department Spends (P, D, C, A) -->
                    <div class="dept-grid">
                        <div class="dept-card">
                            <div class="dept-label" style="color:var(--role-p);">POR</div>
                            <div class="dept-spent" id="spentP">0</div>
                            <div class="dept-count" id="countP">0 slot</div>
                        </div>
                        <div class="dept-card">
                            <div class="dept-label" style="color:var(--role-d);">DIF</div>
                            <div class="dept-spent" id="spentD">0</div>
                            <div class="dept-count" id="countD">0 slot</div>
                        </div>
                        <div class="dept-card">
                            <div class="dept-label" style="color:var(--role-c);">CEN</div>
                            <div class="dept-spent" id="spentC">0</div>
                            <div class="dept-count" id="countC">0 slot</div>
                        </div>
                        <div class="dept-card">
                            <div class="dept-label" style="color:var(--role-a);">ATT</div>
                            <div class="dept-spent" id="spentA">0</div>
                            <div class="dept-count" id="countA">0 slot</div>
                        </div>
                    </div>
                </div>

                <!-- TACTICAL FANTASY STADIUM PITCH (2D) -->
                <div class="tactical-pitch-card">
                    <div class="pitch-top-bar">
                        <div class="pitch-title-badge">
                            <span>🏟️</span>
                            <span>Schieramento Tattico Rosa</span>
                        </div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">
                            <span id="pitchFormationTitle" style="color:var(--primary); font-weight:700;">Formazione Live</span>
                        </div>
                    </div>
                    
                    <div class="pitch-board" id="pitchBoard">
                        <div class="pitch-penalty-top"></div>
                        <div class="pitch-midline"></div>
                        <div class="pitch-penalty-bottom"></div>

                        <!-- Attacco (A) -->
                        <div class="pitch-row pitch-row-a" id="pitchRowA"></div>
                        <!-- Centrocampo (C) -->
                        <div class="pitch-row pitch-row-c" id="pitchRowC"></div>
                        <!-- Difesa (D) -->
                        <div class="pitch-row pitch-row-d" id="pitchRowD"></div>
                        <!-- Portiere (P) -->
                        <div class="pitch-row pitch-row-p" id="pitchRowP"></div>
                    </div>
                </div>

                <!-- Slotted Player Tables by Role -->
                <div class="card">
                    <div class="slot-section">
                        <div class="slot-title"><span style="color:var(--role-p)">PORTIERI (4)</span> <span id="summaryP">0 cr</span></div>
                        <div id="slotsListP"></div>
                    </div>

                    <div class="slot-section">
                        <div class="slot-title"><span style="color:var(--role-d)">DIFENSORI (9)</span> <span id="summaryD">0 cr</span></div>
                        <div id="slotsListD"></div>
                    </div>

                    <div class="slot-section">
                        <div class="slot-title"><span style="color:var(--role-c)">CENTROCAMPISTI (9)</span> <span id="summaryC">0 cr</span></div>
                        <div id="slotsListC"></div>
                    </div>

                    <div class="slot-section">
                        <div class="slot-title"><span style="color:var(--role-a)">ATTACCANTI (7)</span> <span id="summaryA">0 cr</span></div>
                        <div id="slotsListA"></div>
                    </div>
                </div>
            </div>

            <!-- Global Comparison Table View -->
            <div id="globalOverviewView" style="display:none;" class="card">
                <div class="card-header">
                    <div class="card-title">Panoramica Finanziaria Completa</div>
                </div>
                <div style="overflow-x:auto;">
                    <table class="overview-table">
                        <thead>
                            <tr>
                                <th>Squadra</th>
                                <th>Rimasti</th>
                                <th>Max Bid</th>
                                <th>POR</th>
                                <th>DIF</th>
                                <th>CEN</th>
                                <th>ATT</th>
                            </tr>
                        </thead>
                        <tbody id="overviewTableBody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- TAB 6: LISTONE COMPLETO & ANALYTICS -->
        <div id="tab-listone" class="tab-content">
            <div class="pills" id="rolePills">
                <div class="pill active" onclick="setRoleFilter('ALL')">Tutti</div>
                <div class="pill" onclick="setRoleFilter('P')">Portieri (4)</div>
                <div class="pill" onclick="setRoleFilter('D')">Difensori (9)</div>
                <div class="pill" onclick="setRoleFilter('C')">Centrocampisti (9)</div>
                <div class="pill" onclick="setRoleFilter('A')">Attaccanti (7)</div>
            </div>

            <div class="pills" id="fasciaPills">
                <div class="pill active" onclick="setFasciaFilter('ALL')">Tutte le Fasce</div>
                <div class="pill" onclick="setFasciaFilter('1')">1ª Fascia Top</div>
                <div class="pill" onclick="setFasciaFilter('2')">2ª Fascia Semi-Top</div>
                <div class="pill" onclick="setFasciaFilter('3')">3ª Fascia Titolari</div>
                <div class="pill" onclick="setFasciaFilter('4')">4ª Fascia Scommesse</div>
            </div>

            <div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
                <input type="text" id="listSearch" placeholder="Cerca calciatore o squadra..." oninput="renderListone()" style="margin-bottom:0; flex:1; min-width:160px;">
                <button class="btn-secondary" id="filterAvailableOnlyBtn" onclick="toggleFilterAvailableOnly()" style="width:auto; padding:0 12px; white-space:nowrap; font-size:0.8rem; font-weight:700;">
                    Solo Svincolati
                </button>
                <button class="btn-secondary" id="filterTargetsOnlyBtn" onclick="toggleFilterTargetsOnly()" style="width:auto; padding:0 12px; white-space:nowrap; font-size:0.8rem; font-weight:700;">
                    Solo Target
                </button>
            </div>

            <div id="listoneContainer"></div>
        </div>

    </div> <!-- end .container -->
    </div> <!-- end .main-wrapper -->
    </div> <!-- end .app-layout -->

    <!-- TARGET EDIT MODAL -->
    <div id="targetModal" class="modal-backdrop">
        <div class="modal-box">
            <div class="modal-title">
                <span id="targetModalPlayerName">Imposta Target</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeTargetModal()">✕</button>
            </div>
            
            <div style="display:flex; gap:10px; align-items:center; margin-bottom:12px; padding:8px 10px; background:#0b111e; border-radius:6px;">
                <span id="targetModalRole" class="badge"></span>
                <div style="font-size:0.85rem;"><span id="targetModalFair" style="color:var(--gold); font-weight:700;"></span> | <span id="targetModalPts" style="color:var(--text-muted);"></span></div>
            </div>

            <label style="font-size:0.78rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:4px;">PREZZO MASSIMO PERSONALE (CREDITI):</label>
            <input type="number" id="targetModalMaxPrice" value="1" min="1">

            <label style="font-size:0.78rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:4px;">PRIORITÀ DI ACQUISTO:</label>
            <select id="targetModalPriority">
                <option value="1">1ª Fascia: Priorità Assoluta (Must-Have)</option>
                <option value="2">2ª Fascia: Alternativa Valida</option>
                <option value="3">3ª Fascia: Scommessa a Basso Costo / 1 cr</option>
            </select>

            <label style="font-size:0.78rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:4px;">NOTE TATTICHE PERSONALI:</label>
            <textarea id="targetModalNotes" rows="2" placeholder="Es. Da prendere solo in coppia con Esposito..."></textarea>

            <div style="display:flex; gap:8px; margin-top:8px;">
                <button class="btn btn-danger" style="width:35%;" onclick="removeActiveTarget()">Rimuovi</button>
                <button class="btn btn-primary" style="width:65%;" onclick="saveActiveTarget()">Salva Target</button>
            </div>
        </div>
    </div>

    <!-- PROFILE MANAGER MODAL -->
    <div id="profileModal" class="modal-backdrop">
        <div class="modal-box">
            <div class="modal-title">
                <span>Gestione Profilo & Manager</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeProfileModal()">✕</button>
            </div>

            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                Seleziona la tua squadra per gestire la tua strategia e i tuoi target in modo riservato e indipendente.
            </div>

            <label style="font-size:0.78rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:4px;">SQUADRA ATTIVA:</label>
            <select id="profileTeamSelect" onchange="changeActiveProfile(this.value)"></select>

            <div style="margin-top:14px; padding-top:14px; border-top:1px solid var(--border);">
                <button class="btn btn-secondary" onclick="closeProfileModal()">Conferma e Chiudi</button>
            </div>
        </div>
    </div>

    <!-- CUSTOM TACTICAL BLUEPRINT MODAL -->
    <div id="customConfigModal" class="modal-backdrop">
        <div class="modal-box" style="max-width:560px;">
            <div class="modal-title">
                <span>Configurazione Tattica Personalizzata</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeCustomConfigModal()">✕</button>
            </div>

            <!-- Department Budget Allocation -->
            <div style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <b style="font-size:0.85rem; color:var(--primary);">Budget Reparti (Totale 1000 cr)</b>
                    <span id="customAllocTotalBadge" style="font-size:0.75rem; font-weight:800; color:var(--gold);">1000 / 1000 cr</span>
                </div>
                <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:6px;">
                    <div>
                        <label style="font-size:0.68rem; color:var(--role-p); font-weight:700;">POR (cr)</label>
                        <input type="number" id="cfgSplitP" value="80" min="4" max="300" oninput="updateCustomAllocTotal()" style="margin-bottom:0; padding:6px 8px; font-size:0.85rem; text-align:center;">
                    </div>
                    <div>
                        <label style="font-size:0.68rem; color:var(--role-d); font-weight:700;">DIF (cr)</label>
                        <input type="number" id="cfgSplitD" value="120" min="9" max="400" oninput="updateCustomAllocTotal()" style="margin-bottom:0; padding:6px 8px; font-size:0.85rem; text-align:center;">
                    </div>
                    <div>
                        <label style="font-size:0.68rem; color:var(--role-c); font-weight:700;">CEN (cr)</label>
                        <input type="number" id="cfgSplitC" value="250" min="9" max="500" oninput="updateCustomAllocTotal()" style="margin-bottom:0; padding:6px 8px; font-size:0.85rem; text-align:center;">
                    </div>
                    <div>
                        <label style="font-size:0.68rem; color:var(--role-a); font-weight:700;">ATT (cr)</label>
                        <input type="number" id="cfgSplitA" value="550" min="7" max="800" oninput="updateCustomAllocTotal()" style="margin-bottom:0; padding:6px 8px; font-size:0.85rem; text-align:center;">
                    </div>
                </div>
            </div>

            <!-- Role Selector for Slot Settings -->
            <div class="pills" id="customModalRolePills" style="margin-bottom:10px;">
                <div class="pill active" onclick="setCustomModalRole('A')">Attacco (7)</div>
                <div class="pill" onclick="setCustomModalRole('C')">Centrocampo (9)</div>
                <div class="pill" onclick="setCustomModalRole('D')">Difesa (9)</div>
                <div class="pill" onclick="setCustomModalRole('P')">Porta (4)</div>
            </div>

            <div id="customModalSlotsContainer" style="max-height:260px; overflow-y:auto; margin-bottom:12px; padding-right:4px;"></div>

            <div style="display:flex; gap:8px;">
                <button class="btn btn-secondary" style="width:35%; font-size:0.8rem;" onclick="resetCustomConfigToDefault()">Ripristina</button>
                <button class="btn btn-primary" style="width:65%; font-size:0.85rem;" onclick="saveCustomConfigFromModal()">Salva Tattica</button>
            </div>
        </div>
    </div>

    <!-- LEAGUE SETTINGS MODAL -->
    <div id="leagueSettingsModal" class="modal-backdrop">
        <div class="modal-box" style="max-width:580px;">
            <div class="modal-title">
                <span>⚙️ Impostazioni Lega & Crediti</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeLeagueSettingsModal()">✕</button>
            </div>

            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                Configura budget di partenza, numero di slot per ruolo e le squadre partecipanti.
                I prezzi fair e le metriche verranno scalati proporzionalmente al budget scelto.
            </div>

            <!-- Preset Buttons -->
            <div style="margin-bottom:14px;">
                <label style="font-size:0.75rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:6px;">PRESET RAPIDI:</label>
                <div style="display:flex; gap:8px;">
                    <button class="btn-secondary" style="flex:1; padding:8px; font-size:0.8rem;" onclick="applyLeaguePreset(500, {P:3, D:8, C:8, A:6})">
                        🎯 Classico 500cr (25 slot)
                    </button>
                    <button class="btn-secondary" style="flex:1; padding:8px; font-size:0.8rem;" onclick="applyLeaguePreset(1000, {P:4, D:9, C:9, A:7})">
                        👑 Mantra 1000cr (29 slot)
                    </button>
                </div>
            </div>

            <!-- Budget & Slots Grid -->
            <div style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;">
                <div style="margin-bottom:10px;">
                    <label style="font-size:0.75rem; color:var(--gold); font-weight:800; display:block; margin-bottom:4px;">BUDGET INIZIALE (CREDITI):</label>
                    <input type="number" id="settingBudget" value="500" min="100" max="5000" step="50" style="font-size:1.1rem; font-weight:800; text-align:center; color:var(--gold);">
                </div>

                <label style="font-size:0.75rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:6px;">
                    SLOT PER RUOLO (TOTALE: <span id="settingTotalSlotsBadge" style="color:var(--primary); font-weight:800;">25</span>):
                </label>
                <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; text-align:center;">
                    <div>
                        <span style="font-size:0.72rem; color:var(--role-p); font-weight:800;">POR</span>
                        <input type="number" id="settingSlotP" value="3" min="1" max="6" oninput="updateSettingSlotsTotal()" style="margin-bottom:0; text-align:center; font-weight:700;">
                    </div>
                    <div>
                        <span style="font-size:0.72rem; color:var(--role-d); font-weight:800;">DIF</span>
                        <input type="number" id="settingSlotD" value="8" min="1" max="15" oninput="updateSettingSlotsTotal()" style="margin-bottom:0; text-align:center; font-weight:700;">
                    </div>
                    <div>
                        <span style="font-size:0.72rem; color:var(--role-c); font-weight:800;">CEN</span>
                        <input type="number" id="settingSlotC" value="8" min="1" max="15" oninput="updateSettingSlotsTotal()" style="margin-bottom:0; text-align:center; font-weight:700;">
                    </div>
                    <div>
                        <span style="font-size:0.72rem; color:var(--role-a); font-weight:800;">ATT</span>
                        <input type="number" id="settingSlotA" value="6" min="1" max="12" oninput="updateSettingSlotsTotal()" style="margin-bottom:0; text-align:center; font-weight:700;">
                    </div>
                </div>
            </div>

            <!-- Teams List -->
            <div style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <label style="font-size:0.75rem; color:var(--text-muted); font-weight:700;">SQUADRE DELLA LEGA:</label>
                    <button class="btn-secondary" style="width:auto; padding:4px 10px; font-size:0.72rem; font-weight:700;" onclick="addSettingTeam()">+ Aggiungi</button>
                </div>
                <div id="settingTeamsList" style="max-height:180px; overflow-y:auto; display:flex; flex-direction:column; gap:6px;"></div>
            </div>

            <div style="display:flex; gap:8px;">
                <button class="btn btn-secondary" style="width:35%;" onclick="closeLeagueSettingsModal()">Annulla</button>
                <button class="btn btn-primary" style="width:65%;" onclick="saveLeagueSettingsFromModal()">Salva e Applica</button>
            </div>
        </div>
    </div>

    <!-- INFLATION INFO MODAL -->
    <div id="inflationModal" class="modal-backdrop">
        <div class="modal-box" style="max-width:480px;">
            <div class="modal-title">
                <span>📊 Indice Inflazione Mercato Live</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeInflationModal()">✕</button>
            </div>
            <div style="text-align:center; padding:16px 0;">
                <div id="modalInflationNumber" style="font-size:2.4rem; font-weight:900; color:var(--gold);">1.00x</div>
                <div id="modalInflationStatusBadge" style="display:inline-block; padding:4px 12px; border-radius:20px; font-size:0.82rem; font-weight:800; margin-top:4px;">EQUILIBRATO</div>
            </div>
            <div id="modalInflationDesc" style="font-size:0.88rem; color:var(--text-muted); line-height:1.5; margin-bottom:14px; text-align:center;"></div>
            <div style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:12px; font-size:0.8rem; margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                    <span style="color:var(--text-muted);">Crediti Spendibili Extra:</span>
                    <b id="modalDiscretionaryCredits" style="color:var(--gold);">-</b>
                </div>
                <div style="display:flex; justify-content:space-between;">
                    <span style="color:var(--text-muted);">VORP Disponibile Svincolati:</span>
                    <b id="modalRemainingVorp" style="color:var(--primary);">-</b>
                </div>
            </div>
            <button class="btn btn-primary" onclick="closeInflationModal()">Ho Capito</button>
        </div>
    </div>

    <!-- Toast Notification Container -->
    <div id="toastContainer" class="toast-container"></div>

    <!-- ADMIN AUTH MODAL -->
    <div id="adminModal" class="modal-backdrop">
        <div class="modal-box">
            <div class="modal-title">
                <span>Accesso Battitore Asta</span>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeAdminModal()">✕</button>
            </div>

            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                Inserisci la password per abilitare la tab <b>Asta Live</b> ed effettuare chiamate e assegnazioni ufficiali.
            </div>

            <label style="font-size:0.78rem; color:var(--text-muted); font-weight:700; display:block; margin-bottom:4px;">PASSWORD BATTITORE:</label>
            <input type="password" id="adminPasswordInput" placeholder="Inserisci password..." onkeypress="if(event.key==='Enter') submitAdminAuth()">

            <div style="display:flex; gap:8px; margin-top:8px;">
                <button class="btn btn-secondary" style="width:40%;" onclick="closeAdminModal()">Annulla</button>
                <button class="btn btn-primary" style="width:60%;" onclick="submitAdminAuth()">Accedi</button>
            </div>
        </div>
    </div>

    <!-- AI COPILOT DIAGNOSTICS MODAL -->
    <div id="aiDiagnosticsModal" class="modal-backdrop">
        <div class="modal-box" style="max-width:480px;">
            <div class="modal-title">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span>Diagnostica AI Copilot</span>
                    <span id="modalAiBadge" class="brand-tag">STATUS</span>
                </div>
                <button style="background:transparent; border:none; color:var(--text-muted); font-size:1.2rem; cursor:pointer;" onclick="closeAIDiagnosticsModal()">✕</button>
            </div>

            <div style="margin-bottom:12px; font-size:0.80rem; color:var(--text-muted); line-height:1.4;">
                Qui puoi verificare quale motore AI sta alimentando le risposte e configurare le API gratuite (Groq o Gemini) su Vercel a costo zero.
            </div>

            <div id="aiDiagStatusBox" style="background:#0b111e; border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:12px;">
                <div style="font-size:0.75rem; color:var(--text-muted); font-weight:700; margin-bottom:6px;">MOTORE ATTIVO CORRENTE:</div>
                <div id="diagActiveEngine" style="font-size:0.95rem; font-weight:800; color:var(--primary); margin-bottom:6px;">-</div>
                <div id="diagActiveEngineDesc" style="font-size:0.74rem; color:var(--text-muted);">-</div>
            </div>

            <div style="font-size:0.78rem; font-weight:700; color:var(--text-main); margin-bottom:8px;">STATO PROVIDER DISPONIBILI:</div>
            <div id="aiProvidersList" style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;"></div>

            <div style="background:rgba(255,45,117,0.06); border:1px solid rgba(255,45,117,0.25); border-radius:8px; padding:10px; margin-bottom:14px;">
                <div style="font-size:0.75rem; font-weight:800; color:var(--primary); margin-bottom:4px;">💡 Come attivare Groq Free (0$) su Vercel:</div>
                <div style="font-size:0.72rem; color:var(--text-muted); line-height:1.4;">
                    1. Crea una chiave gratis su <a href="https://console.groq.com/keys" target="_blank" style="color:var(--primary); font-weight:700;">console.groq.com</a> (nessuna carta richiesta).<br>
                    2. Nel tuo pannello Vercel &rarr; <i>Settings &rarr; Environment Variables</i>.<br>
                    3. Aggiungi la variabile: <b>GROQ_API_KEY</b> = <code>gsk_...</code>.<br>
                    4. Il bot passerà istantaneamente a <b>Llama 3.3 70B</b> gratis con risposte complete e veloci.
                </div>
            </div>

            <div style="display:flex; gap:8px;">
                <button class="btn btn-secondary" style="width:40%;" onclick="closeAIDiagnosticsModal()">Chiudi</button>
                <button class="btn btn-primary" style="width:60%;" id="btnTestAI" onclick="testAIConnection()">Test Connessione Live</button>
            </div>
            <div id="testAIResult" style="margin-top:8px; font-size:0.75rem; text-align:center; display:none;"></div>
        </div>
    </div>

    <!-- Bottom Navigation -->
    <nav class="bottom-nav">
        <button class="nav-item" id="botNav-draft" onclick="switchTab('draft')" style="display:none;">
            <svg class="nav-svg" viewBox="0 0 24 24"><path d="m14 7 3 3m-9.5 7.5 7-7m-5-5 3.5-3.5a2.121 2.121 0 0 1 3 3L12.5 5.5m-5 5L2 16l6 6 5.5-5.5"></path></svg>
            <div>Asta Live</div>
        </button>
        <button class="nav-item active" id="botNav-targets" onclick="switchTab('targets')">
            <svg class="nav-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>
            <div>Target</div>
        </button>
        <button class="nav-item" id="botNav-ai" onclick="switchTab('ai')">
            <svg class="nav-svg" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            <div>FantaAI</div>
        </button>
        <button class="nav-item" id="botNav-strategy" onclick="switchTab('strategy')">
            <svg class="nav-svg" viewBox="0 0 24 24"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>
            <div>Scala Slot</div>
        </button>
        <button class="nav-item" id="botNav-rosters" onclick="switchTab('rosters')">
            <svg class="nav-svg" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
            <div>Rose</div>
        </button>
        <button class="nav-item" id="botNav-listone" onclick="switchTab('listone')">
            <svg class="nav-svg" viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
            <div>Listone</div>
        </button>
    </nav>

    <script>
        let allPlayers = [];
        let auctionState = {};
        let selectedPlayer = null;
        let currentRoleFilter = 'ALL';
        let currentFasciaFilter = 'ALL';
        let currentTargetRoleFilter = 'ALL';
        let currentSelectedTeamId = 1;
        let currentStratRole = 'A';
        let slotFramework = {};
        let onlyTargetsFilter = false;
        let editingTargetPlayer = null;

        // Market Inflation & Budget scale
        let marketIndexData = { index: 1.0, status: 'EQUILIBRATO', color: 'blue', description: '', discretionary_credits: 0, unassigned_vorp: 0 };
        let activeBudgetScale = 1.0;

        // League settings state
        let currentLeagueSettings = {
            budget: 500,
            roster_slots: { P: 3, D: 8, C: 8, A: 6 },
            teams: []
        };

        // Admin status (persisted in session)
        let isAdmin = sessionStorage.getItem('fanta_is_admin') === 'true';

        // Active Manager Profile (defaults to team ID 1)
        let activeProfileId = parseInt(localStorage.getItem('fanta_active_profile_id')) || 1;

        /* ─────────────────────────────────────────────────────────────
           TOAST NOTIFICATIONS
        ───────────────────────────────────────────────────────────── */
        function showToast(message, type = 'info', duration = 3200) {
            const container = document.getElementById('toastContainer');
            if (!container) return;
            const toast = document.createElement('div');
            toast.className = `toast toast-${type}`;
            const icon = type === 'success' ? '✅' : type === 'danger' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
            toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
            container.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(40px)';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        /* ─────────────────────────────────────────────────────────────
           MARKET INFLATION BADGE & MODAL
        ───────────────────────────────────────────────────────────── */
        function updateMarketBadge(marketInfo) {
            if (!marketInfo) return;
            marketIndexData = marketInfo;
            const badgeText = document.getElementById('marketBadgeText');
            const badgeDot = document.getElementById('marketBadgeDot');
            if (badgeText) badgeText.textContent = `Mercato ${marketInfo.index.toFixed(2)}x`;
            if (badgeDot) {
                badgeDot.className = 'status-dot dot-' + (marketInfo.color || 'blue');
            }
        }

        function showInflationInfoModal() {
            document.getElementById('modalInflationNumber').textContent = `${marketIndexData.index.toFixed(2)}x`;
            const badge = document.getElementById('modalInflationStatusBadge');
            badge.textContent = marketIndexData.status;
            badge.style.background = marketIndexData.color === 'red' ? 'rgba(239,68,68,0.2)' : marketIndexData.color === 'yellow' ? 'rgba(245,158,11,0.2)' : marketIndexData.color === 'green' ? 'rgba(16,185,129,0.2)' : 'rgba(56,189,248,0.2)';
            badge.style.color = marketIndexData.color === 'red' ? 'var(--danger)' : marketIndexData.color === 'yellow' ? 'var(--warning)' : marketIndexData.color === 'green' ? 'var(--success)' : 'var(--primary)';
            document.getElementById('modalInflationDesc').textContent = marketIndexData.description || 'Stato del mercato calcolato in tempo reale.';
            document.getElementById('modalDiscretionaryCredits').textContent = `${marketIndexData.discretionary_credits || 0} cr`;
            document.getElementById('modalRemainingVorp').textContent = `+${marketIndexData.unassigned_vorp || 0} pts`;
            document.getElementById('inflationModal').style.display = 'flex';
        }

        function closeInflationModal() {
            document.getElementById('inflationModal').style.display = 'none';
        }

        /* ─────────────────────────────────────────────────────────────
           LEAGUE SETTINGS MODAL & API
        ───────────────────────────────────────────────────────────── */
        async function openLeagueSettingsModal() {
            try {
                const res = await fetch('/api/settings');
                const data = await res.json();
                if (data.settings) {
                    currentLeagueSettings = data.settings;
                }
            } catch(e) {}
            populateLeagueSettingsModal();
            document.getElementById('leagueSettingsModal').style.display = 'flex';
        }

        function closeLeagueSettingsModal() {
            document.getElementById('leagueSettingsModal').style.display = 'none';
        }

        function populateLeagueSettingsModal() {
            document.getElementById('settingBudget').value = currentLeagueSettings.budget || 500;
            const slots = currentLeagueSettings.roster_slots || { P: 3, D: 8, C: 8, A: 6 };
            document.getElementById('settingSlotP').value = slots.P || 3;
            document.getElementById('settingSlotD').value = slots.D || 8;
            document.getElementById('settingSlotC').value = slots.C || 8;
            document.getElementById('settingSlotA').value = slots.A || 6;
            updateSettingSlotsTotal();
            renderSettingTeamsList();
        }

        function updateSettingSlotsTotal() {
            const p = parseInt(document.getElementById('settingSlotP').value) || 0;
            const d = parseInt(document.getElementById('settingSlotD').value) || 0;
            const c = parseInt(document.getElementById('settingSlotC').value) || 0;
            const a = parseInt(document.getElementById('settingSlotA').value) || 0;
            document.getElementById('settingTotalSlotsBadge').textContent = p + d + c + a;
        }

        function applyLeaguePreset(budget, slots) {
            document.getElementById('settingBudget').value = budget;
            document.getElementById('settingSlotP').value = slots.P;
            document.getElementById('settingSlotD').value = slots.D;
            document.getElementById('settingSlotC').value = slots.C;
            document.getElementById('settingSlotA').value = slots.A;
            updateSettingSlotsTotal();
        }

        function renderSettingTeamsList() {
            const listEl = document.getElementById('settingTeamsList');
            if (!listEl) return;
            const teams = currentLeagueSettings.teams || [];
            listEl.innerHTML = teams.map((t, idx) => `
                <div style="display:flex; gap:8px; align-items:center;">
                    <span style="font-size:0.75rem; color:var(--text-muted); min-width:24px;">#${idx+1}</span>
                    <input type="text" id="settingTeamName_${idx}" value="${t.name}" style="margin-bottom:0; flex:1; padding:6px 10px; font-size:0.85rem;">
                    <label style="display:flex; align-items:center; gap:4px; font-size:0.75rem; color:var(--primary); cursor:pointer; white-space:nowrap;">
                        <input type="radio" name="myTeamRadio" ${t.is_me ? 'checked' : ''} onchange="setMyTeam(${idx})" style="width:auto; margin-bottom:0;">
                        Io
                    </label>
                    <button class="btn-danger" style="width:auto; padding:4px 8px; font-size:0.75rem;" onclick="removeSettingTeam(${idx})" ${teams.length <= 2 ? 'disabled' : ''}>✕</button>
                </div>
            `).join('');
        }

        function setMyTeam(idx) {
            (currentLeagueSettings.teams || []).forEach((t, i) => {
                t.is_me = (i === idx);
            });
        }

        function addSettingTeam() {
            const teams = currentLeagueSettings.teams || [];
            if (teams.length >= 16) {
                showToast("Massimo 16 squadre consentite", "warning");
                return;
            }
            teams.push({ id: teams.length + 1, name: `Squadra ${teams.length + 1}`, is_me: false });
            renderSettingTeamsList();
        }

        function removeSettingTeam(idx) {
            const teams = currentLeagueSettings.teams || [];
            if (teams.length <= 2) return;
            teams.splice(idx, 1);
            teams.forEach((t, i) => { t.id = i + 1; });
            if (!teams.some(t => t.is_me)) teams[0].is_me = true;
            renderSettingTeamsList();
        }

        async function saveLeagueSettingsFromModal() {
            const budget = parseInt(document.getElementById('settingBudget').value) || 500;
            const slots = {
                P: parseInt(document.getElementById('settingSlotP').value) || 3,
                D: parseInt(document.getElementById('settingSlotD').value) || 8,
                C: parseInt(document.getElementById('settingSlotC').value) || 8,
                A: parseInt(document.getElementById('settingSlotA').value) || 6
            };

            const teams = currentLeagueSettings.teams || [];
            teams.forEach((t, idx) => {
                const inp = document.getElementById(`settingTeamName_${idx}`);
                if (inp) t.name = inp.value.trim() || `Squadra ${idx+1}`;
            });

            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ budget, roster_slots: slots, teams })
            });
            const data = await res.json();
            if (data.error) {
                showToast(data.error, 'danger');
                return;
            }

            closeLeagueSettingsModal();
            showToast(data.message || "Impostazioni salvate con successo!", "success");

            if (data.reset) {
                localStorage.removeItem('fanta_lab_auction_state');
                showToast("Asta inizializzata con la nuova configurazione.", "info");
            }

            await fetchState();
            await fetchPlayers();
            renderTeamSelect();
        }

        function getTargetStorageKey() {
            return `fanta_targets_profile_${activeProfileId}`;
        }

        function loadUserTargets() {
            try {
                const saved = localStorage.getItem(getTargetStorageKey());
                return saved ? JSON.parse(saved) : {};
            } catch(e) {
                return {};
            }
        }

        function saveUserTargets(targets) {
            localStorage.setItem(getTargetStorageKey(), JSON.stringify(targets));
        }

        function toggleMobileSidebar() {
            const sb = document.getElementById('appSidebar');
            const bd = document.getElementById('sidebarBackdrop');
            sb.classList.toggle('open');
            bd.classList.toggle('show');
        }

        function updateAdminUI() {
            const sideBtn = document.getElementById('sideNav-draft');
            const botBtn = document.getElementById('botNav-draft');
            const unlockBtn = document.getElementById('adminUnlockBtn');
            const unlockText = document.getElementById('adminBtnText');

            if (isAdmin) {
                if (sideBtn) sideBtn.style.display = 'flex';
                if (botBtn) botBtn.style.display = 'flex';
                if (unlockBtn) unlockBtn.classList.add('unlocked');
                if (unlockText) unlockText.textContent = 'Battitore (Attivo)';
            } else {
                if (sideBtn) sideBtn.style.display = 'none';
                if (botBtn) botBtn.style.display = 'none';
                if (unlockBtn) unlockBtn.classList.remove('unlocked');
                if (unlockText) unlockText.textContent = 'Battitore';
            }
        }

        function openAdminModal() {
            if (isAdmin) {
                if (confirm('Vuoi uscire dalla modalità Battitore?')) {
                    isAdmin = false;
                    sessionStorage.removeItem('fanta_is_admin');
                    updateAdminUI();
                    showToast('Sei tornato in modalità Solo Tracker', 'info');
                    switchTab('targets');
                }
                return;
            }
            document.getElementById('adminPasswordInput').value = '';
            document.getElementById('adminModal').style.display = 'flex';
        }

        function closeAdminModal() {
            document.getElementById('adminModal').style.display = 'none';
        }

        async function submitAdminAuth() {
            const pwd = document.getElementById('adminPasswordInput').value.trim();
            const res = await fetch('/api/auth_admin', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ password: pwd })
            });
            const data = await res.json();
            if (data.success) {
                isAdmin = true;
                sessionStorage.setItem('fanta_is_admin', 'true');
                closeAdminModal();
                updateAdminUI();
                showToast('Accesso Battitore effettuato!', 'success');
                switchTab('draft');
            } else {
                showToast(data.error || 'Password non valida.', 'danger');
            }
        }

        function updateLiveAdvice() {
            const team = (auctionState.teams || []).find(t => t.id === activeProfileId) || (auctionState.teams || [])[0];
            const adviceEl = document.getElementById('sidebarLiveAdvice');
            if (!team || !adviceEl) return;

            const countA = (team.counts && team.counts.A) || 0;
            const countD = (team.counts && team.counts.D) || 0;
            const budgetTotal = auctionState.budget_total || 500;

            if (countA === 0 && team.remaining > (budgetTotal * 0.6)) {
                adviceEl.textContent = `Consiglio Tattico: Sei ancora a 0 punte. Riserva circa il 45-50% del budget (${Math.round(team.remaining*0.48)} cr) per un bomber primario.`;
            } else if (countD < 3 && team.remaining > (budgetTotal * 0.3)) {
                adviceEl.textContent = "Consiglio Tattico: Modificatore difesa decisivo. Punta su difensori con MV elevata prima che i prezzi salgano.";
            } else if (team.remaining < (team.total_slots_left * 4) && team.total_slots_left > 4) {
                adviceEl.textContent = `Consiglio Tattico: Disciplina budget! Ti restano ${team.remaining} cr per ${team.total_slots_left} slot. Chiama a 1 credito.`;
            } else {
                adviceEl.textContent = `Mercato in corso. Indice inflazione: ${marketIndexData.index.toFixed(2)}x (${marketIndexData.status}).`;
            }
        }

        async function init() {
            await fetchState();
            await fetchPlayers();
            fetchAIStatus();
            updateAdminUI();
            updateProfileDisplay();
            renderTeamSelect();
            renderListone();
            renderRosterTeamPills();
            renderRosterTab();
            renderStrategyTab();
            renderTargetsTab();
            setupSearch();

            if (window.location.hash) {
                const tabName = window.location.hash.replace('#', '');
                if (['draft', 'targets', 'ai', 'strategy', 'rosters', 'listone'].includes(tabName)) {
                    switchTab(tabName);
                }
            }

            // Periodic live refresh polling for real-time updates (every 4s)
            setInterval(async () => {
                const res = await fetch('/api/state');
                const data = await res.json();
                if (JSON.stringify(data.state) !== JSON.stringify(auctionState)) {
                    auctionState = data.state;
                    if (data.market_index) updateMarketBadge(data.market_index);
                    updateHeader();
                    updateLiveAdvice();
                    renderRecent();
                    renderRosterTab();
                    renderTargetsTab();
                    renderStrategyTab();
                    renderListone();
                }
            }, 4000);
        }

        async function fetchState() {
            const res = await fetch('/api/state');
            const data = await res.json();
            auctionState = data.state;
            slotFramework = data.slot_framework || {};
            tacticalPresets = data.tactical_presets || tacticalPresets;
            if (data.market_index) updateMarketBadge(data.market_index);
            localStorage.setItem('fanta_lab_auction_state', JSON.stringify(auctionState));
            updateHeader();
            updateProfileDisplay();
            updateLiveAdvice();
            renderRecent();
            renderRosterTab();
            renderStrategyTab();
            renderTargetsTab();
            renderListone();
        }

        async function fetchPlayers() {
            const res = await fetch('/api/players');
            const data = await res.json();
            allPlayers = data.players;
            slotFramework = data.slot_framework || slotFramework;
            tacticalPresets = data.tactical_presets || tacticalPresets;
            if (data.market_index) updateMarketBadge(data.market_index);
            if (data.budget_scale) activeBudgetScale = data.budget_scale;
        }

        function updateHeader() {
            const drafted = Object.keys(auctionState.assigned_players || {}).length;
            document.getElementById('draftedCount').textContent = drafted;
        }

        function updateProfileDisplay() {
            const team = (auctionState.teams || []).find(t => t.id === activeProfileId) || (auctionState.teams || [])[0];
            if (team) {
                document.getElementById('headerProfileName').textContent = team.name;
                const sideName = document.getElementById('sideProfileName');
                const sideBudget = document.getElementById('sideProfileBudget');
                if (sideName) sideName.textContent = team.name;
                if (sideBudget) sideBudget.textContent = `${team.remaining} cr residui (Max: ${team.max_bid} cr)`;
            }
        }

        function switchTab(tabId) {
            // Guard: Draft tab requires admin
            if (tabId === 'draft' && !isAdmin) {
                return;
            }

            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.sidebar-nav-btn').forEach(el => el.classList.remove('active'));

            const targetTab = document.getElementById('tab-' + tabId);
            if (targetTab) targetTab.classList.add('active');

            const botBtn = document.getElementById('botNav-' + tabId);
            if (botBtn) botBtn.classList.add('active');

            const sideBtn = document.getElementById('sideNav-' + tabId);
            if (sideBtn) sideBtn.classList.add('active');

            // Close mobile drawer if open
            const sb = document.getElementById('appSidebar');
            const bd = document.getElementById('sidebarBackdrop');
            if (sb && sb.classList.contains('open')) {
                sb.classList.remove('open');
                bd.classList.remove('show');
            }

            if (tabId === 'targets') renderTargetsTab();
            if (tabId === 'strategy') renderStrategyTab();
            if (tabId === 'rosters') renderRosterTab();
            if (tabId === 'listone') renderListone();
        }

        function setRoleFilter(role) {
            currentRoleFilter = role;
            document.querySelectorAll('#rolePills .pill').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(role === 'ALL' ? 'Tutti' : role));
            });
            renderListone();
        }

        function setFasciaFilter(f) {
            currentFasciaFilter = f;
            document.querySelectorAll('#fasciaPills .pill').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(f === 'ALL' ? 'Tutte' : f + 'ª'));
            });
            renderListone();
        }

        function setTargetRoleFilter(role) {
            currentTargetRoleFilter = role;
            document.querySelectorAll('#targetRolePills .pill').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(role === 'ALL' ? 'Tutti' : role === 'P' ? 'Portieri' : role === 'D' ? 'Difensori' : role === 'C' ? 'Centrocampisti' : 'Attaccanti'));
            });
            renderTargetsTab();
        }

        function setStratRole(role) {
            currentStratRole = role;
            document.querySelectorAll('#stratRolePills .pill').forEach(el => {
                el.classList.toggle('active', el.textContent.includes(role === 'A' ? 'Attacco' : role === 'C' ? 'Centrocampo' : role === 'D' ? 'Difesa' : 'Porta'));
            });
            renderStrategyTab();
        }

        let onlyAvailableFilter = false;

        function toggleFilterAvailableOnly() {
            onlyAvailableFilter = !onlyAvailableFilter;
            const btn = document.getElementById('filterAvailableOnlyBtn');
            if (btn) {
                btn.style.background = onlyAvailableFilter ? 'var(--primary)' : 'var(--surface-elevated)';
                btn.style.color = onlyAvailableFilter ? '#090d16' : 'var(--text-main)';
            }
            renderListone();
        }

        function toggleFilterTargetsOnly() {
            onlyTargetsFilter = !onlyTargetsFilter;
            const btn = document.getElementById('filterTargetsOnlyBtn');
            if (btn) {
                btn.style.background = onlyTargetsFilter ? 'var(--gold)' : 'var(--surface-elevated)';
                btn.style.color = onlyTargetsFilter ? '#090d16' : 'var(--text-main)';
            }
            renderListone();
        }

        function renderTeamSelect() {
            const select = document.getElementById('teamSelect');
            select.innerHTML = (auctionState.teams || []).map(t =>
                `<option value="${t.id}" ${t.id === activeProfileId ? 'selected' : ''}>${t.name} (Rimasti: ${t.remaining} cr | Max Bid: ${t.max_bid} cr)</option>`
            ).join('');
        }

        function changePrice(delta) {
            const inp = document.getElementById('bidPrice');
            let val = parseInt(inp.value) || 1;
            val = Math.max(1, val + delta);
            inp.value = val;
        }

        function setupSearch() {
            const inp = document.getElementById('playerSearch');
            const box = document.getElementById('suggestionsBox');

            inp.addEventListener('input', (e) => {
                const q = e.target.value.trim().toLowerCase();
                if (q.length < 2) {
                    box.style.display = 'none';
                    return;
                }
                const matches = allPlayers.filter(p => !p.is_assigned && (p.player.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))).slice(0, 6);
                if (matches.length === 0) {
                    box.style.display = 'none';
                    return;
                }
                box.innerHTML = matches.map(p => `
                    <div class="suggestion-item" onclick="selectPlayer('${p.player.replace(/'/g, "\\\\'")}')">
                        <div>
                            <span class="badge badge-${p.role}">${p.role}</span>
                            <b>${p.player}</b> <small style="color:var(--text-muted)">(${p.team})</small>
                        </div>
                        <div style="font-weight:800; color:var(--gold);">${p.price_fair_live || p.price_fair_scaled || p.price_fair_1000} cr</div>
                    </div>
                `).join('');
                box.style.display = 'block';
            });
        }

        function selectPlayer(name) {
            selectedPlayer = allPlayers.find(p => p.player === name);
            if (!selectedPlayer) return;

            document.getElementById('suggestionsBox').style.display = 'none';
            document.getElementById('playerSearch').value = selectedPlayer.player;

            const card = document.getElementById('selectedPlayerCard');
            document.getElementById('selRole').className = 'badge badge-' + selectedPlayer.role;
            document.getElementById('selRole').textContent = selectedPlayer.role;
            document.getElementById('selName').textContent = selectedPlayer.player;
            document.getElementById('selTeam').textContent = `(${selectedPlayer.team})`;
            const livePrice = selectedPlayer.price_fair_live || selectedPlayer.price_fair_scaled || selectedPlayer.price_fair_1000;
            document.getElementById('selFair').textContent = `Fair Price Live: ${livePrice} cr`;
            document.getElementById('selSurplus').innerHTML = `Surplus: <span style="color:${selectedPlayer.surplus_value > 0 ? 'var(--success)' : 'var(--danger)'}">${selectedPlayer.surplus_value > 0 ? '+' : ''}${selectedPlayer.surplus_value} cr</span>`;
            card.style.display = 'block';

            document.getElementById('bidPrice').value = selectedPlayer.price_official || 1;
        }

        async function submitAssignment() {
            if (!isAdmin) {
                openAdminModal();
                return;
            }
            if (!selectedPlayer) {
                showToast('Selezionare prima un calciatore.', 'warning');
                return;
            }
            const teamId = document.getElementById('teamSelect').value;
            const price = parseInt(document.getElementById('bidPrice').value) || 1;

            const res = await fetch('/api/assign', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ player: selectedPlayer.player, team_id: teamId, price: price })
            });

            const data = await res.json();
            if (data.error) {
                showToast(data.error, 'danger');
                return;
            }

            const pName = selectedPlayer.player;
            showToast(`Assegnato ${pName} a ${price} crediti!`, 'success');

            selectedPlayer = null;
            document.getElementById('playerSearch').value = '';
            document.getElementById('selectedPlayerCard').style.display = 'none';
            document.getElementById('bidPrice').value = 1;

            await fetchState();
            await fetchPlayers();
            renderTeamSelect();
        }

        async function undoLast() {
            if (!isAdmin) {
                openAdminModal();
                return;
            }
            const res = await fetch('/api/undo', { method: 'POST' });
            const data = await res.json();
            if (data.error) {
                showToast(data.error, 'danger');
                return;
            }
            showToast(`Annullata chiamata di ${data.undone ? data.undone.player : 'giocatore'}`, 'info');
            await fetchState();
            await fetchPlayers();
        }

        function renderRecent() {
            const hist = auctionState.history || [];
            const container = document.getElementById('recentList');
            if (hist.length === 0) {
                container.innerHTML = '<div style="color:var(--text-muted)">Nessuna chiamata registrata.</div>';
                return;
            }
            const teamsMap = {};
            (auctionState.teams || []).forEach(t => teamsMap[t.id] = t.name);

            container.innerHTML = hist.slice(-5).reverse().map(h => `
                <div class="player-row">
                    <div><b>${h.player}</b> &rarr; <span style="color:var(--primary); font-weight:700;">${teamsMap[h.team_id]}</span></div>
                    <div style="font-weight:800; color:var(--gold);">${h.price} cr</div>
                </div>
            `).join('');
        }

        /* ─────────────────────────────────────────────────────────────
           TACTICAL AI CONVERSATIONAL CHATBOT ENGINE
        ───────────────────────────────────────────────────────────── */
        const AI_AVATAR_HTML = `<div class="chat-msg-avatar" style="width:32px; height:32px; border-radius:50%; background:linear-gradient(135deg, #0284c7, #4f46e5); display:flex; align-items:center; justify-content:center; flex-shrink:0; border:1.5px solid var(--primary);"><svg style="width:16px; height:16px; stroke:#ffffff; fill:none; stroke-width:2;" viewBox="0 0 24 24"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path></svg></div>`;

        function setAIQuery(queryText) {
            document.getElementById('aiInputPrompt').value = queryText;
            submitAIQuery();
        }

        function clearAIChat() {
            const stream = document.getElementById('chatMessagesStream');
            stream.innerHTML = `
                <div class="chat-msg ai">
                    ${AI_AVATAR_HTML}
                    <div class="chat-bubble">
                        <b>Chat azzerata.</b><br>
                        Come posso aiutarti? Chiedimi confronti tra giocatori, diagnosi sul tuo bilancio o scommesse per completare la rosa!
                    </div>
                </div>
            `;
        }

        async function submitAIQuery() {
            const input = document.getElementById('aiInputPrompt');
            const prompt = input.value.trim();
            if (!prompt) return;

            const stream = document.getElementById('chatMessagesStream');
            const btn = document.getElementById('btnSubmitAI');

            // 1. Append User Message Bubble
            const userMsg = document.createElement('div');
            userMsg.className = 'chat-msg user';
            userMsg.innerHTML = `<div class="chat-bubble">${escapeHTML(prompt)}</div>`;
            stream.appendChild(userMsg);

            input.value = '';
            if (btn) btn.disabled = true;

            // 2. Append Temporary Loading Bubble
            const loadingMsg = document.createElement('div');
            loadingMsg.className = 'chat-msg ai';
            loadingMsg.id = 'aiChatLoadingBubble';
            loadingMsg.innerHTML = `
                ${AI_AVATAR_HTML}
                <div class="chat-bubble" style="color:var(--text-muted); font-style:italic;">
                    Sto analizzando i dati del listone, VORP e formazioni reali...
                </div>
            `;
            stream.appendChild(loadingMsg);
            stream.scrollTop = stream.scrollHeight;

            try {
                const res = await fetch('/api/ai_query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt: prompt, profile_id: activeProfileId })
                });

                if (!res.ok) {
                    const errTxt = await res.text();
                    throw new Error(`Server ${res.status}: ${errTxt.slice(0, 100)}`);
                }

                const data = await res.json();

                // Remove loading bubble
                const loadElem = document.getElementById('aiChatLoadingBubble');
                if (loadElem) loadElem.remove();

                // 3. Append AI Response Bubble
                const aiMsg = document.createElement('div');
                aiMsg.className = 'chat-msg ai';
                aiMsg.innerHTML = `
                    ${AI_AVATAR_HTML}
                    <div class="chat-bubble">
                        ${renderAIChatContent(data)}
                    </div>
                `;
                stream.appendChild(aiMsg);
            } catch(e) {
                console.error("AI Chat Exception:", e);
                const loadElem = document.getElementById('aiChatLoadingBubble');
                if (loadElem) loadElem.remove();

                const errBubble = document.createElement('div');
                errBubble.className = 'chat-msg ai';
                errBubble.innerHTML = `
                    ${AI_AVATAR_HTML}
                    <div class="chat-bubble" style="color:var(--danger); font-size:0.85rem;">
                        <b>Errore di elaborazione:</b> ${escapeHTML(e.message || "Riprova con un'altra domanda.")}
                    </div>
                `;
                stream.appendChild(errBubble);
            }

            if (btn) btn.disabled = false;
            stream.scrollTop = stream.scrollHeight;
        }

        function escapeHTML(str) {
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        function formatMarkdownText(text) {
            if (!text) return '';
            let raw = escapeHTML(text);

            const nl = String.fromCharCode(10);
            // 1. Process Markdown Tables (| col1 | col2 |)
            const lines = raw.split(nl);
            let inTable = false;
            let tableHtml = '';
            let processedLines = [];

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();
                if (line.startsWith('|') && line.endsWith('|')) {
                    const cells = line.slice(1, -1).split('|').map(c => c.trim());
                    // Skip separator row (|---|---|)
                    if (cells.every(c => /^:?-+:?$/.test(c))) {
                        continue;
                    }
                    if (!inTable) {
                        inTable = true;
                        tableHtml = '<div style="overflow-x:auto; margin:8px 0;"><table class="ai-table" style="width:100%; border-collapse:collapse; font-size:0.80rem; text-align:left;">';
                        tableHtml += '<thead><tr style="border-bottom:1.5px solid var(--border); background:rgba(255,45,117,0.12); color:var(--text-main);">';
                        cells.forEach(c => { tableHtml += `<th style="padding:6px 8px; font-weight:800;">${c}</th>`; });
                        tableHtml += '</tr></thead><tbody>';
                    } else {
                        tableHtml += '<tr style="border-bottom:1px solid rgba(255,255,255,0.06);">';
                        cells.forEach(c => { tableHtml += `<td style="padding:5px 8px;">${c}</td>`; });
                        tableHtml += '</tr>';
                    }
                } else {
                    if (inTable) {
                        tableHtml += '</tbody></table></div>';
                        processedLines.push(tableHtml);
                        inTable = false;
                        tableHtml = '';
                    }
                    processedLines.push(line);
                }
            }
            if (inTable) {
                tableHtml += '</tbody></table></div>';
                processedLines.push(tableHtml);
            }

            let formatted = processedLines.join(nl);
            // Headers
            formatted = formatted.replace(/^### (.*$)/gim, '<h4 style="color:var(--primary); font-size:0.95rem; margin:10px 0 4px 0;">$1</h4>');
            formatted = formatted.replace(/^## (.*$)/gim, '<h3 style="color:var(--text-main); font-size:1.02rem; margin:12px 0 6px 0;">$1</h3>');
            // Bold & Italic
            formatted = formatted.replace(/\\*\\*(.*?)\\*\\*/g, '<b style="color:var(--text-main);">$1</b>');
            formatted = formatted.replace(/\\*(.*?)\\*/g, '<i style="color:var(--text-muted);">$1</i>');
            // Bullet Points
            formatted = formatted.replace(/^\\s*-\\s+(.*$)/gim, '<div style="display:flex; gap:6px; margin-bottom:3px;"><span style="color:var(--primary);">&bull;</span><span>$1</span></div>');
            // Spacing
            formatted = formatted.split(nl + nl).join('<div style="height:8px;"></div>');
            formatted = formatted.split(nl).join('<br>');
            return formatted;
        }

        function renderAIChatContent(data) {
            if (!data) return 'Nessuna risposta disponibile.';
            const engineTag = `<div style="margin-top:8px; padding-top:6px; border-top:1px dashed rgba(255,255,255,0.08); font-size:0.68rem; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center;"><span>Fonte: <b style="color:var(--primary);">${data.engine || 'Regole Tattiche Offline'}</b></span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>`;

            try {
                if (data.type === 'llm_chat') {
                    return `<div>${formatMarkdownText(data.text || '')}${engineTag}</div>`;
                }

                if (data.type === 'roster_diagnostic') {
                    const s = data.stats || {};
                    const free = s.free_slots || {};
                    return `
                        <div>
                            <div style="font-weight:800; font-size:1.02rem; color:var(--primary); margin-bottom:8px;">${data.title || 'Diagnosi Rosa'}</div>
                            <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:6px; background:#0b111e; padding:8px 10px; border-radius:8px; margin-bottom:10px; font-size:0.82rem;">
                                <div>Crediti Residui: <b style="color:var(--gold);">${s.remaining || 0} cr</b></div>
                                <div>Max Rilancio: <b style="color:var(--danger);">${s.max_bid || 0} cr</b></div>
                                <div>Slot Liberi: <b>${free.total || 0}</b> (P:${free.P || 0} D:${free.D || 0} C:${free.C || 0} A:${free.A || 0})</div>
                                <div>Media cr/slot: <b>${s.avg_per_slot || 0} cr</b></div>
                            </div>
                            <div style="margin-bottom:8px;">
                                ${(data.advice || []).map(a => `<div style="margin-bottom:4px; font-size:0.85rem;">&bull; ${a}</div>`).join('')}
                            </div>
                            <div style="background:rgba(56,189,248,0.08); border-left:3px solid var(--primary); padding:8px 10px; border-radius:4px; font-size:0.85rem;">
                                ${data.verdict || ''}
                            </div>
                            ${engineTag}
                        </div>
                    `;
                }

                if (data.type === 'comparison') {
                    const players = data.players || [];
                    return `
                        <div>
                            <div style="font-weight:800; font-size:1rem; color:var(--primary); margin-bottom:10px;">${data.title || 'Confronto'}</div>
                            <div style="display:grid; grid-template-columns:${players.length > 2 ? 'repeat(3, 1fr)' : 'repeat(2, 1fr)'}; gap:8px; margin-bottom:10px;">
                                ${players.map(p => `
                                    <div style="background:#0b111e; padding:10px 8px; border-radius:8px; border:1px solid var(--border); font-size:0.82rem;">
                                        <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                                            <span class="badge badge-${p.role}">${p.role}</span>
                                            <b>${p.name}</b>
                                        </div>
                                        <div style="color:var(--text-muted); font-size:0.75rem; margin-bottom:4px;">${p.team} - ${p.starts || 0} start</div>
                                        <div>Punti Attesi: <b>${p.pts_exp || 0} pts</b></div>
                                        <div>Fair Price: <b style="color:var(--gold);">${p.fair_1000 || 1} cr</b></div>
                                        <div>VORP: <b style="color:var(--success);">+${p.vorp || 0}</b></div>
                                    </div>
                                `).join('')}
                            </div>
                            <div style="background:rgba(56,189,248,0.08); border-left:3px solid var(--primary); padding:8px 10px; border-radius:4px; font-size:0.85rem;">
                                ${formatMarkdownText(data.verdict || '')}
                            </div>
                            ${engineTag}
                        </div>
                    `;
                }

                if (data.type === 'player_deepdive') {
                    const p = data.player || {};
                    return `
                        <div>
                            <div style="font-weight:800; font-size:1.02rem; color:var(--gold); margin-bottom:8px;">${data.title}</div>
                            <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; text-align:center; margin-bottom:10px;">
                                <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                                    <div style="font-size:0.7rem; color:var(--text-muted); font-weight:700;">PROIEZIONE P50</div>
                                    <div style="font-size:1.1rem; font-weight:800; color:var(--primary);">${p.pts_exp || 0} pts</div>
                                </div>
                                <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                                    <div style="font-size:0.7rem; color:var(--text-muted); font-weight:700;">FAIR PRICE 1000</div>
                                    <div style="font-size:1.1rem; font-weight:800; color:var(--gold);">${p.fair_1000 || 1} cr</div>
                                </div>
                                <div style="background:#0b111e; padding:8px; border-radius:6px; border:1px solid var(--border);">
                                    <div style="font-size:0.7rem; color:var(--text-muted); font-weight:700;">TITOLARITÀ REALE</div>
                                    <div style="font-size:1.1rem; font-weight:800; color:var(--success);">${p.starts || 0} start</div>
                                </div>
                            </div>
                            <div style="background:rgba(56,189,248,0.08); border-left:3px solid var(--gold); padding:8px 10px; border-radius:4px; font-size:0.85rem; margin-bottom:8px;">
                                ${formatMarkdownText(data.verdict || '')}
                            </div>
                            ${engineTag}
                        </div>
                    `;
                }

                if (data.type === 'recommendations') {
                    const players = data.players || [];
                    return `
                        <div>
                            <div style="font-weight:800; font-size:1rem; color:var(--success); margin-bottom:8px;">${data.title}</div>
                            <div style="margin-bottom:10px;">
                                ${players.map(p => `
                                    <div class="candidate-mini-row" style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; margin-bottom:4px; background:#0b111e; border-radius:6px; border:1px solid var(--border);">
                                        <div style="display:flex; align-items:center; gap:8px;">
                                            <span class="badge badge-${p.role}">${p.role}</span>
                                            <b>${p.name}</b> <small style="color:var(--text-muted);">(${p.team})</small>
                                        </div>
                                        <div style="text-align:right;">
                                            <span style="color:var(--gold); font-weight:800; font-size:0.95rem;">${p.fair_1000} cr</span>
                                            <span style="color:var(--primary); font-size:0.78rem; margin-left:6px;">+${p.vorp} vorp</span>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                            <div style="background:rgba(16,185,129,0.08); border-left:3px solid var(--success); padding:8px 10px; border-radius:4px; font-size:0.85rem;">
                                ${formatMarkdownText(data.verdict || '')}
                            </div>
                            ${engineTag}
                        </div>
                    `;
                }

                // Generic fallback for any unexpected type or structure
                const fallbackText = data.text || data.verdict || JSON.stringify(data);
                return `<div>${formatMarkdownText(fallbackText)}${engineTag}</div>`;
            } catch(renderErr) {
                console.error("renderAIChatContent Error:", renderErr);
                return `<div>${formatMarkdownText(data.text || data.verdict || 'Risposta elaborata.')}${engineTag}</div>`;
            }
        }

        async function fetchAIStatus() {
            try {
                const res = await fetch('/api/ai_status');
                const diag = await res.json();
                const dot = document.getElementById('aiEngineStatusDot');
                const lbl = document.getElementById('aiActiveEngineLabel');
                if (diag.has_llm) {
                    if (dot) dot.className = 'status-dot dot-green';
                    if (lbl) {
                        lbl.textContent = diag.active_engine;
                        lbl.style.color = 'var(--success)';
                    }
                } else {
                    if (dot) dot.className = 'status-dot dot-yellow';
                    if (lbl) {
                        lbl.textContent = 'Fallback Matematico (Nessuna API Key)';
                        lbl.style.color = 'var(--gold)';
                    }
                }
                return diag;
            } catch(e) {
                return null;
            }
        }

        async function openAIDiagnosticsModal() {
            const diag = await fetchAIStatus();
            const modal = document.getElementById('aiDiagnosticsModal');
            if (!modal || !diag) return;

            document.getElementById('diagActiveEngine').textContent = diag.active_engine || 'Nessuno';
            document.getElementById('diagActiveEngineDesc').textContent = diag.has_llm 
                ? 'LLM Cloud attivo: le risposte sono generate con intelligenza artificiale conversazionale.' 
                : 'Attualmente attivo il motore a regole locali: riconosce confronti, schede giocatore, formazioni e diagnosi, ma non genera risposte libere complesse.';

            const badge = document.getElementById('modalAiBadge');
            if (badge) {
                badge.textContent = diag.has_llm ? 'ONLINE' : 'OFFLINE MODE';
                badge.style.color = diag.has_llm ? 'var(--success)' : 'var(--gold)';
            }

            const list = document.getElementById('aiProvidersList');
            if (list && diag.providers) {
                list.innerHTML = Object.entries(diag.providers).map(([k, p]) => `
                    <div style="background:#0b111e; border:1px solid var(--border); border-radius:6px; padding:8px 10px; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:700; font-size:0.82rem; color:var(--text-main);">${p.name}</div>
                            <div style="font-size:0.70rem; color:var(--text-muted);">Env Vercel: <code>${p.env_var}</code></div>
                        </div>
                        <span class="badge ${p.configured ? 'badge-D' : 'badge-P'}" style="font-size:0.72rem;">
                            ${p.configured ? '✓ Configurato' : 'Non configurato'}
                        </span>
                    </div>
                `).join('');
            }

            document.getElementById('testAIResult').style.display = 'none';
            modal.classList.add('active');
        }

        function closeAIDiagnosticsModal() {
            const modal = document.getElementById('aiDiagnosticsModal');
            if (modal) modal.classList.remove('active');
        }

        async function testAIConnection() {
            const btn = document.getElementById('btnTestAI');
            const resBox = document.getElementById('testAIResult');
            if (btn) btn.disabled = true;
            if (resBox) {
                resBox.style.display = 'block';
                resBox.innerHTML = '<span style="color:var(--text-muted);">Ping live ai provider in corso...</span>';
            }

            const t0 = performance.now();
            try {
                const res = await fetch('/api/ai_test');
                const testData = await res.json();
                const latency = Math.round(performance.now() - t0);
                
                let details = '';
                if (testData.groq) {
                    details += `<div>Groq: <b style="color:${testData.groq.ok ? 'var(--success)' : 'var(--danger)'};">${testData.groq.msg}</b></div>`;
                }
                if (testData.gemini) {
                    details += `<div>Gemini: <b style="color:${testData.gemini.ok ? 'var(--success)' : 'var(--danger)'};">${testData.gemini.msg}</b></div>`;
                }

                if (resBox) {
                    resBox.innerHTML = `
                        <div style="background:#090d16; border:1px solid var(--border); border-radius:6px; padding:8px; text-align:left; font-size:0.75rem;">
                            <div style="font-weight:800; color:var(--text-main); margin-bottom:4px;">Esito Ping (${latency}ms):</div>
                            ${details}
                        </div>
                    `;
                }
                fetchAIStatus();
            } catch(e) {
                if (resBox) {
                    resBox.innerHTML = `<span style="color:var(--danger); font-weight:700;">✕ Errore di chiamata: ${e.message}</span>`;
                }
            }
            if (btn) btn.disabled = false;
        }

        /* ─────────────────────────────────────────────────────────────
           TARGETS & WISHLIST MANAGEMENT
        ───────────────────────────────────────────────────────────── */
        function openTargetModal(playerName) {
            const p = allPlayers.find(x => x.player === playerName);
            if (!p) return;
            editingTargetPlayer = p;

            const targets = loadUserTargets();
            const existing = targets[p.player] || {};

            document.getElementById('targetModalPlayerName').textContent = p.player;
            document.getElementById('targetModalRole').className = 'badge badge-' + p.role;
            document.getElementById('targetModalRole').textContent = p.role;
            document.getElementById('targetModalFair').textContent = `Fair: ${p.price_fair_1000} cr`;
            document.getElementById('targetModalPts').textContent = `Punti Attesi: ${p.pts_exp} pts`;
            document.getElementById('targetModalMaxPrice').value = existing.max_price || p.price_fair_1000 || 1;
            document.getElementById('targetModalPriority').value = existing.priority || 1;
            document.getElementById('targetModalNotes').value = existing.notes || '';

            document.getElementById('targetModal').style.display = 'flex';
        }

        function closeTargetModal() {
            document.getElementById('targetModal').style.display = 'none';
            editingTargetPlayer = null;
        }

        function saveActiveTarget() {
            if (!editingTargetPlayer) return;
            const pName = editingTargetPlayer.player;
            const maxPrice = parseInt(document.getElementById('targetModalMaxPrice').value) || 1;
            const priority = parseInt(document.getElementById('targetModalPriority').value) || 1;
            const notes = document.getElementById('targetModalNotes').value.trim();

            const targets = loadUserTargets();
            targets[pName] = {
                player: pName,
                role: editingTargetPlayer.role,
                team: editingTargetPlayer.team,
                max_price: maxPrice,
                priority: priority,
                notes: notes,
                created_at: new Date().toISOString()
            };
            saveUserTargets(targets);
            closeTargetModal();

            renderListone();
            renderTargetsTab();
            renderStrategyTab();
        }

        function removeActiveTarget() {
            if (!editingTargetPlayer) return;
            const pName = editingTargetPlayer.player;
            const targets = loadUserTargets();
            if (targets[pName]) {
                delete targets[pName];
                saveUserTargets(targets);
            }
            closeTargetModal();

            renderListone();
            renderTargetsTab();
            renderStrategyTab();
        }

        function renderTargetsTab() {
            const targets = loadUserTargets();
            const targetNames = Object.keys(targets);
            const assignedMap = auctionState.assigned_players || {};

            let sumTier1 = 0;
            let sumTier2 = 0;
            let availableCount = 0;
            const coverage = {P: 0, D: 0, C: 0, A: 0};
            const targetSpend = {P: 0, D: 0, C: 0, A: 0};

            const targetList = [];

            targetNames.forEach(name => {
                const t = targets[name];
                const p = allPlayers.find(x => x.player === name) || {};
                const isAssigned = name in assignedMap;
                const assignment = assignedMap[name];
                const isMine = assignment && assignment.team_id === activeProfileId;

                const role = t.role || p.role || 'C';
                const maxPrice = t.max_price || p.price_fair_1000 || 1;
                const priority = t.priority || 1;

                if (!isAssigned) {
                    availableCount++;
                    if (priority === 1) sumTier1 += maxPrice;
                    else if (priority === 2) sumTier2 += maxPrice;
                }

                coverage[role] = (coverage[role] || 0) + 1;
                targetSpend[role] = (targetSpend[role] || 0) + maxPrice;

                targetList.push({
                    ...t,
                    pts_exp: p.pts_exp || 0,
                    price_fair_1000: p.price_fair_1000 || maxPrice,
                    is_assigned: isAssigned,
                    is_mine: isMine,
                    assignment: assignment
                });
            });

            // Update Financial Commitment Badges
            document.getElementById('commitTier1').textContent = `${sumTier1} cr`;
            document.getElementById('commitTier2').textContent = `${sumTier2} cr`;
            document.getElementById('targetAvailableCount').textContent = `${availableCount}/${targetNames.length}`;
            document.getElementById('targetCommitmentBadge').textContent = `Totale Top: ${sumTier1} cr`;

            // Update Slot Coverage
            document.getElementById('targetCoverageP').textContent = `${coverage.P}/4`;
            document.getElementById('targetSpentP').textContent = `${targetSpend.P} cr max`;
            document.getElementById('targetCoverageD').textContent = `${coverage.D}/9`;
            document.getElementById('targetSpentD').textContent = `${targetSpend.D} cr max`;
            document.getElementById('targetCoverageC').textContent = `${coverage.C}/9`;
            document.getElementById('targetSpentC').textContent = `${targetSpend.C} cr max`;
            document.getElementById('targetCoverageA').textContent = `${coverage.A}/7`;
            document.getElementById('targetSpentA').textContent = `${targetSpend.A} cr max`;

            // Filter targets by role
            const filtered = targetList.filter(t => currentTargetRoleFilter === 'ALL' || t.role === currentTargetRoleFilter);
            filtered.sort((a,b) => {
                if (a.priority !== b.priority) return a.priority - b.priority;
                return b.max_price - a.max_price;
            });

            const container = document.getElementById('targetsListContainer');
            if (filtered.length === 0) {
                container.innerHTML = '<div class="card" style="text-align:center; color:var(--text-muted); font-size:0.85rem;">Nessun target salvato. Clicca sul mirino accanto a qualsiasi calciatore nel Listone per aggiungerlo.</div>';
                return;
            }

            container.innerHTML = filtered.map(t => {
                let statusBadge = '<span style="color:var(--primary); font-weight:800; font-size:0.82rem;">DISPONIBILE</span>';
                if (t.is_mine) {
                    statusBadge = `<span style="color:var(--success); font-weight:800; font-size:0.82rem;">ACQUISTATO (${t.assignment.price} cr)</span>`;
                } else if (t.is_assigned) {
                    statusBadge = `<span style="color:var(--danger); font-weight:700; font-size:0.82rem;">PERSO &rarr; ${t.assignment.team_name} (${t.assignment.price} cr)</span>`;
                }

                return `
                    <div class="card" style="padding:14px; margin-bottom:10px; ${t.is_assigned && !t.is_mine ? 'opacity:0.45;' : ''}">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                            <div>
                                <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                                    <span class="tier-badge tier-${t.priority}">PRIORITÀ ${t.priority}</span>
                                    <span class="badge badge-${t.role}">${t.role}</span>
                                    <b style="font-size:1.05rem;">${t.player}</b>
                                    <small style="color:var(--text-muted); font-size:0.85rem;">(${t.team})</small>
                                </div>
                                <div style="font-size:0.85rem; color:var(--text-muted); margin-top:4px;">
                                    Fair Price: <b style="color:var(--gold);">${t.price_fair_1000} cr</b> | Punti Attesi: <b style="color:var(--text-main);">${t.pts_exp} pts</b>
                                </div>
                                ${t.notes ? `<div style="font-size:0.82rem; color:var(--gold); margin-top:5px; font-style:italic;">Note: ${t.notes}</div>` : ''}
                            </div>
                            <div style="text-align:right; flex-shrink:0;">
                                <div style="font-size:1.2rem; font-weight:800; color:var(--gold);">Max: ${t.max_price} cr</div>
                                <div>${statusBadge}</div>
                                <button class="btn-secondary" style="margin-top:8px; padding:6px 12px; font-size:0.82rem; font-weight:700; width:auto;" onclick="openTargetModal('${t.player.replace(/'/g, "\\\\'")}')">Modifica</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function exportTargetsJSON() {
            const targets = loadUserTargets();
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(targets, null, 2));
            const downloadAnchor = document.createElement('a');
            downloadAnchor.setAttribute("href", dataStr);
            downloadAnchor.setAttribute("download", `fanta_targets_profile_${activeProfileId}.json`);
            document.body.appendChild(downloadAnchor);
            downloadAnchor.click();
            downloadAnchor.remove();
        }

        /* ─────────────────────────────────────────────────────────────
           STRATEGY & SLOT DISCIPLINE PLANNER (CUSTOMIZABLE BLUEPRINTS)
        ───────────────────────────────────────────────────────────── */
        let tacticalPresets = {};
        let currentTacticId = localStorage.getItem('fanta_tactic_profile_' + activeProfileId) || 'trazione_anteriore';
        let slotExpandedMap = {}; // Tracks expanded state for free cluster navigation
        let customModalRole = 'A';

        function getCustomTacticStorageKey() {
            return `fanta_custom_tactic_profile_${activeProfileId}`;
        }

        function getCustomTacticConfig() {
            try {
                const saved = localStorage.getItem(getCustomTacticStorageKey());
                if (saved) return JSON.parse(saved);
            } catch(e) {}
            return tacticalPresets['custom'] || null;
        }

        function saveCustomTacticConfig(cfg) {
            localStorage.setItem(getCustomTacticStorageKey(), JSON.stringify(cfg));
        }

        function renderTacticPills() {
            const container = document.getElementById('tacticPresetPills');
            if (!container || !tacticalPresets || Object.keys(tacticalPresets).length === 0) return;

            container.innerHTML = Object.values(tacticalPresets).map(t => `
                <div class="pill ${t.id === currentTacticId ? 'active' : ''}" onclick="setTacticalPreset('${t.id}')">
                    ${t.name}
                </div>
            `).join('');
        }

        function setTacticalPreset(tacticId) {
            currentTacticId = tacticId;
            localStorage.setItem('fanta_tactic_profile_' + activeProfileId, tacticId);
            renderTacticPills();
            renderStrategyTab();
        }

        function toggleSlotExpansion(role, slotNum) {
            const key = `${role}_${slotNum}`;
            slotExpandedMap[key] = !slotExpandedMap[key];
            renderStrategyTab();
        }

        function openCustomConfigModal() {
            const customCfg = getCustomTacticConfig() || tacticalPresets['custom'];
            if (!customCfg) return;

            // Load splits
            const split = customCfg.split || {};
            const parseNum = (str, def) => parseInt(String(str)) || def;

            document.getElementById('cfgSplitP').value = parseNum(split.P, 80);
            document.getElementById('cfgSplitD').value = parseNum(split.D, 120);
            document.getElementById('cfgSplitC').value = parseNum(split.C, 250);
            document.getElementById('cfgSplitA').value = parseNum(split.A, 550);

            updateCustomAllocTotal();
            setCustomModalRole(customModalRole || 'A');
            document.getElementById('customConfigModal').style.display = 'flex';
        }

        function closeCustomConfigModal() {
            document.getElementById('customConfigModal').style.display = 'none';
        }

        function updateCustomAllocTotal() {
            const p = parseInt(document.getElementById('cfgSplitP').value) || 0;
            const d = parseInt(document.getElementById('cfgSplitD').value) || 0;
            const c = parseInt(document.getElementById('cfgSplitC').value) || 0;
            const a = parseInt(document.getElementById('cfgSplitA').value) || 0;
            const tot = p + d + c + a;

            const badge = document.getElementById('customAllocTotalBadge');
            badge.textContent = `${tot} / 1000 cr`;
            if (tot === 1000) {
                badge.style.color = 'var(--success)';
            } else if (tot > 1000) {
                badge.style.color = 'var(--danger)';
            } else {
                badge.style.color = 'var(--gold)';
            }
        }

        function setCustomModalRole(role) {
            customModalRole = role;
            const pills = document.querySelectorAll('#customModalRolePills .pill');
            const roles = ['A', 'C', 'D', 'P'];
            pills.forEach((p, idx) => {
                if (roles[idx] === role) p.classList.add('active');
                else p.classList.remove('active');
            });
            renderCustomModalSlots(role);
        }

        function renderCustomModalSlots(role) {
            const customCfg = getCustomTacticConfig() || tacticalPresets['custom'];
            const slots = (customCfg && customCfg.slots && customCfg.slots[role]) || [];
            const container = document.getElementById('customModalSlotsContainer');

            container.innerHTML = slots.map((s, idx) => `
                <div style="background:#0b111e; border:1px solid var(--border); border-radius:6px; padding:8px; margin-bottom:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <b style="font-size:0.8rem; color:var(--primary);">Slot #${s.slot}</b>
                        <input type="text" id="customSlotName_${role}_${idx}" value="${s.name.replace(/"/g, '&quot;')}" style="margin-bottom:0; padding:4px 6px; font-size:0.75rem; width:70%;">
                    </div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:6px; font-size:0.72rem;">
                        <div>
                            <label style="color:var(--text-muted); display:block; font-size:0.65rem;">Target (testo)</label>
                            <input type="text" id="customSlotTarget_${role}_${idx}" value="${s.target_budget || '1 cr'}" style="margin-bottom:0; padding:4px 6px; font-size:0.75rem;">
                        </div>
                        <div>
                            <label style="color:var(--danger); display:block; font-size:0.65rem; font-weight:700;">Stop-Loss (cr)</label>
                            <input type="number" id="customSlotMax_${role}_${idx}" value="${s.max_limit || 2}" min="1" max="600" style="margin-bottom:0; padding:4px 6px; font-size:0.75rem;">
                        </div>
                        <div>
                            <label style="color:var(--text-muted); display:block; font-size:0.65rem;">Fascia Minima</label>
                            <select id="customSlotFascia_${role}_${idx}" style="margin-bottom:0; padding:4px 6px; font-size:0.75rem;">
                                <option value="1" ${s.fascia === 1 ? 'selected' : ''}>1ª Fascia</option>
                                <option value="2" ${s.fascia === 2 ? 'selected' : ''}>2ª Fascia</option>
                                <option value="3" ${s.fascia === 3 ? 'selected' : ''}>3ª Fascia</option>
                                <option value="4" ${s.fascia === 4 ? 'selected' : ''}>4ª Fascia</option>
                            </select>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function saveCustomConfigFromModal() {
            const customCfg = JSON.parse(JSON.stringify(getCustomTacticConfig() || tacticalPresets['custom']));

            const p = parseInt(document.getElementById('cfgSplitP').value) || 80;
            const d = parseInt(document.getElementById('cfgSplitD').value) || 120;
            const c = parseInt(document.getElementById('cfgSplitC').value) || 250;
            const a = parseInt(document.getElementById('cfgSplitA').value) || 550;

            customCfg.split = {
                "P": `${p} cr (${Math.round(p/10)}%)`,
                "D": `${d} cr (${Math.round(d/10)}%)`,
                "C": `${c} cr (${Math.round(c/10)}%)`,
                "A": `${a} cr (${Math.round(a/10)}%)`
            };

            // Save slots for current modal role
            const role = customModalRole;
            const slots = customCfg.slots[role] || [];
            slots.forEach((s, idx) => {
                const nameEl = document.getElementById(`customSlotName_${role}_${idx}`);
                const targetEl = document.getElementById(`customSlotTarget_${role}_${idx}`);
                const maxEl = document.getElementById(`customSlotMax_${role}_${idx}`);
                const fasciaEl = document.getElementById(`customSlotFascia_${role}_${idx}`);

                if (nameEl) s.name = nameEl.value.trim();
                if (targetEl) s.target_budget = targetEl.value.trim();
                if (maxEl) s.max_limit = parseInt(maxEl.value) || s.max_limit;
                if (fasciaEl) s.fascia = parseInt(fasciaEl.value) || s.fascia;
            });

            saveCustomTacticConfig(customCfg);
            closeCustomConfigModal();
            renderStrategyTab();
        }

        function resetCustomConfigToDefault() {
            if (confirm('Vuoi ripristinare la strategia personalizzata ai valori iniziali?')) {
                localStorage.removeItem(getCustomTacticStorageKey());
                openCustomConfigModal();
                renderStrategyTab();
            }
        }

        function renderStrategyTab() {
            const myTeam = (auctionState.teams || []).find(t => t.id === activeProfileId) || (auctionState.teams || [])[0];
            if (!myTeam) return;

            document.getElementById('strategyRemainingBadge').textContent = `Budget: ${myTeam.remaining} cr`;

            renderTacticPills();

            let tactic = tacticalPresets[currentTacticId] || Object.values(tacticalPresets)[0];
            if (currentTacticId === 'custom') {
                tactic = getCustomTacticConfig() || tactic;
            }
            if (!tactic) return;

            // Toggle custom config button
            const btnCustom = document.getElementById('btnCustomConfig');
            if (btnCustom) {
                btnCustom.style.display = currentTacticId === 'custom' ? 'block' : 'none';
            }

            // Render tactic overview card
            document.getElementById('tacticTitle').textContent = tactic.name;
            document.getElementById('tacticBadge').textContent = tactic.badge;
            document.getElementById('tacticDesc').textContent = tactic.description;

            const split = tactic.split || {};
            document.getElementById('splitPOR').textContent = split.P || '-';
            document.getElementById('splitDIF').textContent = split.D || '-';
            document.getElementById('splitCEN').textContent = split.C || '-';
            document.getElementById('splitATT').textContent = split.A || '-';

            const role = currentStratRole;
            const myRosterRole = (myTeam.roster || []).filter(p => p.role === role);
            const myCount = myRosterRole.length;

            const roleSlots = (tactic.slots && tactic.slots[role]) || (slotFramework[role] || []);
            const container = document.getElementById('strategySlotsContainer');

            let html = '';
            roleSlots.forEach((slotCfg, idx) => {
                const isAcquired = idx < myCount;
                const isCurrentTarget = idx === myCount;
                const slotKey = `${role}_${slotCfg.slot}`;
                
                // Default expanded if it's the current target, or if explicitly toggled by user
                const isExpanded = slotExpandedMap[slotKey] !== undefined ? slotExpandedMap[slotKey] : (isCurrentTarget || !isAcquired);

                const availableRole = allPlayers.filter(p => !p.is_assigned && p.role === role);
                const userTargets = loadUserTargets();

                // Candidate ranking tailored by role & tactical blueprint
                const candidates = availableRole.filter(p => {
                    if (slotCfg.slot === 1) return p.price_fair_1000 >= (slotCfg.max_limit * 0.45);
                    if (slotCfg.slot === 2) return p.price_fair_1000 <= (slotCfg.max_limit * 1.35) && p.price_fair_1000 >= 30;
                    if (slotCfg.slot === 3) return p.price_fair_1000 <= (slotCfg.max_limit * 1.4) && p.price_fair_1000 >= 15;
                    return p.price_fair_1000 <= slotCfg.max_limit * 2;
                }).sort((a,b) => {
                    const aTarget = a.player in userTargets ? 1 : 0;
                    const bTarget = b.player in userTargets ? 1 : 0;
                    if (aTarget !== bTarget) return bTarget - aTarget;

                    if (currentTacticId === 'modificatore_ferro' && role === 'D') {
                        return (b.pts_exp * 1.5 + b.starts_2627 * 5) - (a.pts_exp * 1.5 + a.starts_2627 * 5);
                    } else if (currentTacticId === 'centrocampo_dominante' && role === 'C') {
                        return (b.pts_exp + b.vorp) - (a.pts_exp + a.vorp);
                    } else if (currentTacticId === 'moneyball_value') {
                        return (b.surplus_value + b.vorp) - (a.surplus_value + a.vorp);
                    } else {
                        return b.price_fair_1000 - a.price_fair_1000;
                    }
                }).slice(0, 6);

                let acquiredHtml = '';
                if (isAcquired) {
                    const acquiredPlayer = myRosterRole[idx];
                    acquiredHtml = `
                        <div style="font-size:0.95rem; font-weight:700; color:var(--text-main); margin-top:6px; padding:10px 12px; background:#0b111e; border-radius:8px;">
                            ${acquiredPlayer.player} <small style="color:var(--text-muted); font-size:0.85rem;">(${acquiredPlayer.team} - ${acquiredPlayer.pts_exp} pts | Spesi: ${acquiredPlayer.price} cr)</small>
                        </div>
                    `;
                }

                html += `
                    <div class="plan-step-card ${isCurrentTarget ? 'active-target' : ''} ${isAcquired ? 'completed' : ''}" style="margin-bottom:10px;">
                        <div class="plan-header" onclick="toggleSlotExpansion('${role}', ${slotCfg.slot})">
                            <div class="plan-slot-title">
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <span style="font-size:1.02rem; font-weight:800; color:${isAcquired ? 'var(--success)' : (isCurrentTarget ? 'var(--primary)' : 'var(--text-main)')};">
                                        Slot #${slotCfg.slot} ${isAcquired ? '✓' : ''}
                                    </span>
                                    <span style="font-size:0.88rem; color:var(--text-muted); font-weight:600;">${slotCfg.name.split(':')[1] || slotCfg.name}</span>
                                </div>
                            </div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <div class="plan-budget-badge">
                                    Target: ${slotCfg.target_budget}
                                </div>
                                <span style="font-size:0.85rem; color:var(--text-muted); font-weight:800;">${isExpanded ? '▲' : '▼'}</span>
                            </div>
                        </div>

                        ${acquiredHtml}

                        ${isExpanded ? `
                            <div style="margin-top:10px; border-top:1px dashed var(--border); padding-top:10px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                                    <span style="font-size:0.82rem; color:var(--danger); font-weight:800; text-transform:uppercase;">
                                        TETTO STOP-LOSS: Max ${slotCfg.max_limit} cr
                                    </span>
                                    <span style="font-size:0.78rem; color:var(--text-muted); font-weight:600;">
                                        ${candidates.length} candidati disponibili
                                    </span>
                                </div>

                                <div>
                                    ${candidates.map(c => `
                                        <div class="candidate-mini-row" onclick="quickSelectPlayer('${c.player.replace(/'/g, "\\\\'")}')">
                                            <div style="display:flex; align-items:center; gap:8px; min-width:0;">
                                                <button class="target-icon-btn ${c.player in userTargets ? 'active' : ''}" style="width:28px; height:28px;" onclick="event.stopPropagation(); openTargetModal('${c.player.replace(/'/g, "\\\\'")}')">
                                                    <svg class="nav-svg" style="width:16px; height:16px;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="2"></circle></svg>
                                                </button>
                                                <b style="font-size:0.98rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${c.player}</b>
                                                <small style="color:var(--text-muted); font-size:0.82rem; flex-shrink:0;">(${c.team})</small>
                                            </div>
                                            <div style="text-align:right; flex-shrink:0;">
                                                <span style="color:var(--gold); font-weight:800; font-size:1rem;">${c.price_fair_1000} cr</span>
                                                <span style="color:var(--text-muted); font-size:0.8rem; margin-left:4px;">(${c.pts_exp} pts)</span>
                                            </div>
                                        </div>
                                    `).join('')}
                                    ${candidates.length === 0 ? '<div style="font-size:0.85rem; color:var(--text-muted); font-style:italic; padding:6px;">Tutti i calciatori di questo cluster sono già stati assegnati.</div>' : ''}
                                </div>
                            </div>
                        ` : ''}
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function quickSelectPlayer(name) {
            if (isAdmin) {
                selectPlayer(name);
                switchTab('draft');
            } else {
                openTargetModal(name);
            }
        }

        /* ─────────────────────────────────────────────────────────────
           ROSTER INCASILING & DEPARTMENT SPEND TAB
        ───────────────────────────────────────────────────────────── */
        function renderRosterTeamPills() {
            const container = document.getElementById('teamFilterPills');
            const teams = auctionState.teams || [];
            let html = teams.map(t =>
                `<div class="pill ${t.id === currentSelectedTeamId ? 'active' : ''}" onclick="selectRosterTeam(${t.id})">${t.name}${t.id === activeProfileId ? ' (Tua)' : ''}</div>`
            ).join('');
            html += `<div class="pill ${currentSelectedTeamId === 'ALL' ? 'active' : ''}" onclick="selectRosterTeam('ALL')">Panoramica Globale</div>`;
            container.innerHTML = html;
        }

        function selectRosterTeam(teamId) {
            currentSelectedTeamId = teamId;
            renderRosterTeamPills();
            renderRosterTab();
        }

        function renderRosterTab() {
            if (currentSelectedTeamId === 'ALL') {
                document.getElementById('singleTeamView').style.display = 'none';
                document.getElementById('globalOverviewView').style.display = 'block';
                renderGlobalOverview();
                return;
            }

            document.getElementById('singleTeamView').style.display = 'block';
            document.getElementById('globalOverviewView').style.display = 'none';

            const teams = auctionState.teams || [];
            const team = teams.find(t => t.id === currentSelectedTeamId) || teams[0];
            if (!team) return;

            const budgetTotal = auctionState.budget_total || 1000;
            const struct = auctionState.roster_structure || {P: 4, D: 9, C: 9, A: 7};
            const totalRosterSlots = Object.values(struct).reduce((a, b) => a + b, 0);

            document.getElementById('rosterTeamName').textContent = team.name + (team.id === activeProfileId ? ' (Tua Squadra)' : '');
            document.getElementById('rosterSlotsProgress').textContent = `${team.roster.length}/${totalRosterSlots} Slot occupati (Spesi: ${team.spent} cr)`;
            document.getElementById('rosterRemaining').textContent = `${team.remaining} cr`;
            document.getElementById('rosterMaxBid').textContent = `Max Bid: ${team.max_bid} cr`;

            // Financial HUD calculations
            const spentPercent = Math.min(100, Math.round((team.spent / budgetTotal) * 100));
            const hudProgressEl = document.getElementById('hudSquadProgress');
            if (hudProgressEl) hudProgressEl.style.width = `${spentPercent}%`;

            const hudSpentTotalEl = document.getElementById('hudSpentTotal');
            if (hudSpentTotalEl) hudSpentTotalEl.textContent = `${team.spent} cr`;

            const hudSpentPercentEl = document.getElementById('hudSpentPercent');
            if (hudSpentPercentEl) hudSpentPercentEl.textContent = `${spentPercent}%`;

            const teamVorp = (team.roster || []).reduce((acc, p) => acc + (parseFloat(p.vorp || p.vorp_points) || 0), 0);
            const hudTotalVorpEl = document.getElementById('hudTotalVorp');
            if (hudTotalVorpEl) hudTotalVorpEl.textContent = `${teamVorp >= 0 ? '+' : ''}${teamVorp.toFixed(1)}`;

            const spent = team.spent_by_role || {"P":0,"D":0,"C":0,"A":0};
            document.getElementById('spentP').textContent = `${spent.P || 0} cr`;
            document.getElementById('countP').textContent = `${team.counts.P}/${struct.P || 4} slot`;
            document.getElementById('spentD').textContent = `${spent.D || 0} cr`;
            document.getElementById('countD').textContent = `${team.counts.D}/${struct.D || 9} slot`;
            document.getElementById('spentC').textContent = `${spent.C || 0} cr`;
            document.getElementById('countC').textContent = `${team.counts.C}/${struct.C || 9} slot`;
            document.getElementById('spentA').textContent = `${spent.A || 0} cr`;
            document.getElementById('countA').textContent = `${team.counts.A}/${struct.A || 7} slot`;

            document.getElementById('summaryP').textContent = `${spent.P || 0} cr (${team.counts.P}/${struct.P || 4})`;
            document.getElementById('summaryD').textContent = `${spent.D || 0} cr (${team.counts.D}/${struct.D || 9})`;
            document.getElementById('summaryC').textContent = `${spent.C || 0} cr (${team.counts.C}/${struct.C || 9})`;
            document.getElementById('summaryA').textContent = `${spent.A || 0} cr (${team.counts.A}/${struct.A || 7})`;

            renderRoleSlots(team, 'P', struct.P || 4, 'slotsListP');
            renderRoleSlots(team, 'D', struct.D || 9, 'slotsListD');
            renderRoleSlots(team, 'C', struct.C || 9, 'slotsListC');
            renderRoleSlots(team, 'A', struct.A || 7, 'slotsListA');

            // Render Tactical 2D Stadium Pitch
            renderTacticalPitch(team, struct);
        }

        function renderTacticalPitch(team, struct) {
            const roster = team.roster || [];
            const playersByRole = {
                P: roster.filter(p => p.role === 'P'),
                D: roster.filter(p => p.role === 'D'),
                C: roster.filter(p => p.role === 'C'),
                A: roster.filter(p => p.role === 'A')
            };

            const dCount = playersByRole.D.length;
            const cCount = playersByRole.C.length;
            const aCount = playersByRole.A.length;
            const formTitle = `${Math.min(5, Math.max(3, dCount || 3))}-${Math.min(5, Math.max(3, cCount || 4))}-${Math.min(4, Math.max(2, aCount || 3))}`;
            const formEl = document.getElementById('pitchFormationTitle');
            if (formEl) formEl.textContent = `Modulo ${formTitle} (${roster.length} acquistati)`;

            const renderPitchLine = (role, containerId, maxDisplay) => {
                const container = document.getElementById(containerId);
                if (!container) return;
                const players = playersByRole[role] || [];
                let html = '';

                players.slice(0, maxDisplay).forEach(p => {
                    const shortName = p.player.length > 9 ? p.player.substring(0, 8) + '…' : p.player;
                    html += `
                        <div class="pitch-node" onclick="openTargetModal('${p.player.replace(/'/g, "\\\\'")}')" title="${p.player} (${p.team}) - ${p.price} cr">
                            <div class="pitch-jersey role-${role}">${role}</div>
                            <div class="pitch-node-name">${shortName}</div>
                            <div class="pitch-node-price">${p.price} cr</div>
                        </div>
                    `;
                });

                const emptySlots = Math.max(0, maxDisplay - players.length);
                for (let i = 0; i < Math.min(emptySlots, 4); i++) {
                    html += `
                        <div class="pitch-node pitch-node-empty" title="Slot ${role} disponibile">
                            <div class="pitch-jersey">+</div>
                            <div class="pitch-node-name">Slot</div>
                        </div>
                    `;
                }
                container.innerHTML = html;
            };

            renderPitchLine('A', 'pitchRowA', 3);
            renderPitchLine('C', 'pitchRowC', 4);
            renderPitchLine('D', 'pitchRowD', 4);
            renderPitchLine('P', 'pitchRowP', 1);
        }

        function renderRoleSlots(team, role, totalSlots, containerId) {
            const players = (team.roster || []).filter(p => p.role === role);
            const container = document.getElementById(containerId);
            let html = '';

            for (let i = 0; i < totalSlots; i++) {
                if (i < players.length) {
                    const p = players[i];
                    html += `
                        <div class="slot-row">
                            <div class="slot-player">
                                <span class="slot-num">#${i+1}</span>
                                <span class="badge badge-${role}">${role}</span>
                                <b>${p.player}</b>
                                <small style="color:var(--text-muted)">(${p.team})</small>
                            </div>
                            <div style="text-align:right;">
                                <span class="slot-price">${p.price} cr</span>
                                <span style="font-size:0.72rem; color:var(--text-muted); margin-left:6px;">(${p.pts_exp} pts)</span>
                            </div>
                        </div>
                    `;
                } else {
                    html += `
                        <div class="slot-row empty">
                            <div style="display:flex; align-items:center; gap:6px;">
                                <span class="slot-num">#${i+1}</span>
                                <span>Slot Libero</span>
                            </div>
                            <div style="font-size:0.72rem;">1 cr min</div>
                        </div>
                    `;
                }
            }
            container.innerHTML = html;
        }

        function renderGlobalOverview() {
            const teams = auctionState.teams || [];
            const tbody = document.getElementById('overviewTableBody');
            tbody.innerHTML = teams.map(t => {
                const s = t.spent_by_role || {P:0, D:0, C:0, A:0};
                return `
                    <tr style="${t.id === activeProfileId ? 'background:rgba(56,189,248,0.08); font-weight:700;' : ''}">
                        <td><b>${t.name}</b> <small style="color:var(--text-muted)">(${t.roster.length}/29)</small></td>
                        <td style="color:var(--gold); font-weight:800;">${t.remaining}</td>
                        <td style="color:var(--danger); font-weight:800;">${t.max_bid}</td>
                        <td>${s.P || 0} <small style="color:var(--text-muted)">(${t.counts.P}/4)</small></td>
                        <td>${s.D || 0} <small style="color:var(--text-muted)">(${t.counts.D}/9)</small></td>
                        <td>${s.C || 0} <small style="color:var(--text-muted)">(${t.counts.C}/9)</small></td>
                        <td>${s.A || 0} <small style="color:var(--text-muted)">(${t.counts.A}/7)</small></td>
                    </tr>
                `;
            }).join('');
        }

        /* ─────────────────────────────────────────────────────────────
           LISTONE & ANALYTICS TAB
        ───────────────────────────────────────────────────────────── */
        function renderListone() {
            const q = (document.getElementById('listSearch')?.value || '').toLowerCase();
            const userTargets = loadUserTargets();
            const assigned = auctionState.assigned_players || {};

            const filtered = allPlayers.filter(p => {
                const isAssigned = p.is_assigned || (p.player in assigned);
                if (onlyAvailableFilter && isAssigned) return false;
                if (onlyTargetsFilter && !(p.player in userTargets)) return false;
                if (currentRoleFilter !== 'ALL' && p.role !== currentRoleFilter) return false;
                if (currentFasciaFilter !== 'ALL' && String(p.fascia) !== String(currentFasciaFilter)) return false;
                if (q && !p.player.toLowerCase().includes(q) && !p.team.toLowerCase().includes(q)) return false;
                return true;
            });

            const container = document.getElementById('listoneContainer');
            if (filtered.length === 0) {
                container.innerHTML = '<div class="card" style="text-align:center; color:var(--text-muted); padding:24px;">Nessun calciatore trovato con i filtri selezionati.</div>';
                return;
            }

            container.innerHTML = filtered.map(p => {
                const isAssigned = p.is_assigned || (p.player in assigned);
                const assignmentInfo = assigned[p.player] || {};
                const isTarget = p.player in userTargets;
                const targetInfo = userTargets[p.player] || {};

                const fairLive = p.price_fair_live || p.price_fair_scaled || p.price_fair_1000;
                const fairScaled = p.price_fair_scaled || p.price_fair_1000;

                const isStarter = p.is_starter_2627 === 1 || p.is_starter_2627 === true || p.is_starter_2627 === "1";

                return `
                    <div class="player-row role-${p.role}" style="${isAssigned ? 'opacity:0.42;' : ''}">
                        <div class="player-info">
                            <div class="player-name">
                                <button class="target-icon-btn ${isTarget ? 'active' : ''}" onclick="openTargetModal('${p.player.replace(/'/g, "\\\\'")}')" title="Aggiungi/Modifica Target">
                                    <svg class="nav-svg" style="width:14px; height:14px;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="2"></circle></svg>
                                </button>
                                <span class="badge badge-${p.role}">${p.role}</span>
                                <span style="font-family:'Outfit',sans-serif; font-weight:700; font-size:1.05rem;">${p.player}</span>
                                <small style="color:var(--text-muted); font-weight:600;">(${p.team})</small>
                                ${isStarter ? `<span class="scout-tag-starter">✓ Titolare</span>` : ''}
                                ${isTarget ? `<span class="tier-badge tier-${targetInfo.priority}">T${targetInfo.priority} (Max ${targetInfo.max_price}cr)</span>` : ''}
                                ${isAssigned ? `<span style="color:var(--danger); font-size:0.75rem; font-weight:700; margin-left:4px;">ASSEGNATO (${assignmentInfo.team_name || ''} - ${assignmentInfo.price || ''} cr)</span>` : ''}
                            </div>
                            <div class="player-meta">
                                <span>Punti Attesi: <b>${p.pts_exp}</b></span>
                                <span style="color:var(--border);">|</span>
                                <span class="scout-vorp-badge">VORP +${p.vorp}</span>
                                <span style="color:var(--border);">|</span>
                                <span>Range: ${p.pts_floor} - ${p.pts_ceil}</span>
                            </div>
                        </div>
                        <div class="player-stats">
                            <div class="scout-price-box">
                                <div class="player-fair" title="Fair Price Live">${fairLive} <span style="font-size:0.7rem; font-weight:700;">cr</span></div>
                            </div>
                            <div style="font-size:0.7rem; color:var(--text-muted); margin-top:2px;">
                                ${fairLive !== fairScaled ? `Base: ${fairScaled}cr` : `Uff: ${p.price_official}cr`}
                            </div>
                            <div class="player-vorp" style="color:${p.surplus_value > 0 ? 'var(--success)' : 'var(--danger)'}">
                                ${p.surplus_value > 0 ? '+' : ''}${p.surplus_value} cr
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        /* ─────────────────────────────────────────────────────────────
           PROFILE SWITCHER
        ───────────────────────────────────────────────────────────── */
        function openProfileModal() {
            const select = document.getElementById('profileTeamSelect');
            select.innerHTML = (auctionState.teams || []).map(t =>
                `<option value="${t.id}" ${t.id === activeProfileId ? 'selected' : ''}>${t.name} (ID: ${t.id})</option>`
            ).join('');
            document.getElementById('profileModal').style.display = 'flex';
        }

        function closeProfileModal() {
            document.getElementById('profileModal').style.display = 'none';
        }

        function changeActiveProfile(teamId) {
            activeProfileId = parseInt(teamId);
            localStorage.setItem('fanta_active_profile_id', activeProfileId);
            currentSelectedTeamId = activeProfileId;
            updateProfileDisplay();
            updateLiveAdvice();
            renderTeamSelect();
            renderRosterTeamPills();
            renderRosterTab();
            renderStrategyTab();
            renderTargetsTab();
            renderListone();
        }

        window.onload = init;
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        bot_name=BOT_NAME,
        bot_subtitle=BOT_SUBTITLE,
        bot_avatar_text=BOT_AVATAR_TEXT,
        bot_avatar_image=BOT_AVATAR_IMAGE,
        bot_badge=BOT_BADGE,
        bot_greeting=BOT_GREETING,
        is_personal=IS_PERSONAL
    )


def main():
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    print("\n" + "=" * 70)
    print("  Spectre - FantaMoneyball — Centro Decisionale Asta & Strategia (PRO)")
    print("  Regole: 1.000 Crediti | Struttura Roster 4-9-9-7 (29 Giocatori)")
    print("=" * 70)
    print(f"\n  Accesso Desktop: http://localhost:5050")
    print(f"  Accesso Mobile:  http://{local_ip}:5050 (stessa rete Wi-Fi)\n")

    app.run(host="0.0.0.0", port=5050, debug=False)


if __name__ == "__main__":
    main()
