#!/usr/bin/env python3
"""
fanta-lab — Configurazione centralizzata
Tutti i parametri, costanti e mapping usati dalla pipeline.
"""

import os

# ──────────────────────────────────────────────────────────────────────
# PATH
# ──────────────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(PROJECT_DIR, "data")
EXAMPLES_DIR = os.path.join(PROJECT_DIR, "examples")
os.makedirs(DATA_DIR, exist_ok=True)

# File quotazioni ufficiali — aggiornare ad ogni nuova release
QUOTAZIONI_FILENAME = "Quotazioni_Fantacalcio_Stagione_2026_27_latest.xlsx"
QUOTAZIONI_PATH     = os.path.join(DATA_DIR, QUOTAZIONI_FILENAME)

# Output
DATASET_FINALE_CSV   = os.path.join(DATA_DIR, "dataset_finale.csv")
INJURIES_CACHE_JSON  = os.path.join(DATA_DIR, "tm_injuries_cache.json")
INJURIES_CSV         = os.path.join(DATA_DIR, "storico_infortuni.csv")
FORMAZIONI_CSV       = os.path.join(DATA_DIR, "formazioni_2627.csv")
OUTPUT_EXCEL         = os.path.join(DATA_DIR, "analisi_fantacalcio_completa.xlsx")

# Storico
STORICO_RAW_CSV      = os.path.join(DATA_DIR, "storico_giocatori_raw.csv")
STORICO_AGG_CSV      = os.path.join(DATA_DIR, "storico_giocatori_aggregato.csv")
STORICO_FILT_CSV     = os.path.join(DATA_DIR, "storico_giocatori_filtrato.csv")
SQUADRE_RAW_CSV      = os.path.join(DATA_DIR, "storico_squadre_raw.csv")
SQUADRE_AGG_CSV      = os.path.join(DATA_DIR, "storico_squadre_aggregato.csv")
UNDERSTAT_RAW_CSV    = os.path.join(DATA_DIR, "understat_raw.csv")
UNDERSTAT_AGG_CSV    = os.path.join(DATA_DIR, "understat_aggregato.csv")

# ──────────────────────────────────────────────────────────────────────
# STAGIONI
# ──────────────────────────────────────────────────────────────────────
# Stagioni da scrapare (fantacalcio.it). Aggiornare all'inizio di ogni stagione.
SEASONS_FC = [
    "2025-26", "2024-25", "2023-24", "2022-23", "2021-22",
    "2020-21", "2019-20", "2018-19", "2017-18", "2016-17", "2015-16",
]

# Stagioni football-data.co.uk (codici per URL)
SEASONS_FD = {
    "2025-26": "2526", "2024-25": "2425", "2023-24": "2324",
    "2022-23": "2223", "2021-22": "2122", "2020-21": "2021",
    "2019-20": "1920", "2018-19": "1819", "2017-18": "1718",
    "2016-17": "1617", "2015-16": "1516",
}

# Stagioni Understat (anno di inizio)
UNDERSTAT_SEASONS = ["2025", "2024", "2023", "2022"]

# Stagioni filtro infortuni Transfermarkt
INJURY_SEASONS_FILTER = ["25/26", "24/25", "23/24"]

# ──────────────────────────────────────────────────────────────────────
# MAPPING SQUADRE
# ──────────────────────────────────────────────────────────────────────
# Sigla 3 lettere → nome completo per vari contesti
TEAM_ABBR_MAP = {
    "Roma": "ROM", "Inter": "INT", "Milan": "MIL", "Juventus": "JUV",
    "Napoli": "NAP", "Atalanta": "ATA", "Lazio": "LAZ", "Fiorentina": "FIO",
    "Bologna": "BOL", "Torino": "TOR", "Udinese": "UDI", "Genoa": "GEN",
    "Cagliari": "CAG", "Empoli": "EMP", "Verona": "VER", "Parma": "PAR",
    "Como": "COM", "Monza": "MON", "Lecce": "LEC", "Venezia": "VEN",
    "Sassuolo": "SAS", "Frosinone": "FRO",
}

# Transfermarkt: sigla → nome inglese
TEAM_TM_MAP = {
    "INT": "Inter", "MIL": "Milan", "JUV": "Juventus", "NAP": "Napoli",
    "ROM": "Roma", "LAZ": "Lazio", "ATA": "Atalanta", "FIO": "Fiorentina",
    "BOL": "Bologna", "TOR": "Torino", "UDI": "Udinese", "GEN": "Genoa",
    "CAG": "Cagliari", "EMP": "Empoli", "VER": "Verona", "PAR": "Parma",
    "COM": "Como", "MON": "Monza", "LEC": "Lecce", "VEN": "Venezia",
    "SAS": "Sassuolo", "FRO": "Frosinone",
}

# football-data.co.uk: nome completo → sigla
TEAM_FD_MAP = {
    "Atalanta": "ATA", "Bologna": "BOL", "Cagliari": "CAG", "Como": "COM",
    "Cremonese": "CRE", "Empoli": "EMP", "Fiorentina": "FIO",
    "Frosinone": "FRO", "Genoa": "GEN", "Hellas Verona": "HEL",
    "Inter": "INT", "Juventus": "JUV", "Lazio": "LAZ", "Lecce": "LEC",
    "Milan": "MIL", "Monza": "MON", "Napoli": "NAP", "Parma": "PAR",
    "Roma": "ROM", "Salernitana": "SAL", "Sampdoria": "SAM",
    "Sassuolo": "SAS", "Spezia": "SPE", "Torino": "TOR",
    "Udinese": "UDI", "Venezia": "VEN", "Verona": "VER",
}

# ──────────────────────────────────────────────────────────────────────
# MATCH FUZZY MANUALI
# ──────────────────────────────────────────────────────────────────────
# Giocatori con nomi ambigui o diversi tra fonti (nome_excel → nome_storico)
MANUAL_FUZZY_MAP = {
    "Chalobah T.":   "Chalobah",
    "Colombo L.":    None,
    "Correia T.":    "Correia",
    "Cuenca A.":     None,
    "Diallo O.":     "Diallo Am.",
    "El Azzouzi A.": "El Azzouzi",
    "El Azzouzi O.": None,
    "Gelli F.":      "Gelli",
    "Gelli J.":      None,
    "Oyono A.":      "Oyono",
    "Oyono J.":      None,
    "Ramos G.":      "Ramos",
    "Rrahmani Al.":  "Rrahmani",
    "Stankovic A.":  "Stankovic F.",
    "Traore Hj.":    "Traore' Hj.",
}

# ──────────────────────────────────────────────────────────────────────
# SCORE COMPOSITO — PESI
# ──────────────────────────────────────────────────────────────────────
# Pesi dei componenti dello score composito (somma = 1.0)
SCORE_WEIGHTS = {
    "mv_storica":       0.20,   # Media voto ponderata ultimi 3 anni
    "mv_attesa":        0.20,   # Media voto attesa modello stagione corrente
    "fv_attesa":        0.15,   # Fantavoto atteso modello
    "prob_bonus":       0.20,   # Probabilità bonus ≥ 8
    "xg":               0.10,   # Expected Goals media 3 anni
    "availability":     0.10,   # Disponibilità (% presenze)
    "prezzo_inverso":   0.05,   # Inversamente proporzionale al prezzo (valore)
}

# Malus infortuni: impatto massimo sullo score
INJURY_MALUS_MAX_IMPACT = 0.15   # -15% max sullo score composito
INJURY_DAYS_DENOMINATOR = 180    # Giorni per normalizzare la penalità
INJURY_GRAVE_THRESHOLD  = 60    # Giorni per definire infortunio "grave"
INJURY_GRAVE_PENALTY    = 0.30   # Penalità aggiuntiva per infortunio grave

# ──────────────────────────────────────────────────────────────────────
# SCRAPING
# ──────────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}

RATE_LIMIT_SEC = 1.5             # Pausa tra richieste scraping
TM_MAX_WORKERS = 6               # Thread paralleli Transfermarkt
