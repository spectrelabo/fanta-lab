#!/usr/bin/env python3
"""
FASE 4 — Merge multi-sorgente + calcolo Score Composito.

Unisce il listone base (da Quotazioni) con:
  1. Storico giocatori aggregato (11 stagioni fantacalcio.it)
  2. Understat xG/xA
  3. Indici offensivi/difensivi squadra
  4. Cache infortuni Transfermarkt

Calcola lo score composito e applica il malus infortuni.

Output:
  - dataset_finale.csv
  - storico_infortuni.csv
"""

import os, sys, re, json, warnings, difflib, unicodedata
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import importlib
_mod03 = importlib.import_module("pipeline.03_update_listone")
load_quotazioni = _mod03.load_quotazioni
build_listone = _mod03.build_listone

warnings.filterwarnings("ignore")


def normalize(s):
    """Normalizza un nome rimuovendo accenti e convertendo in lowercase."""
    s = str(s).lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s


def safe_norm(series):
    """Normalizza una serie numerica in [0, 1]."""
    s = pd.to_numeric(series, errors='coerce').fillna(0)
    mn, mx = s.min(), s.max()
    return (s - mn) / (mx - mn) if mx > mn else pd.Series(0.5, index=s.index)


def merge_storico(df, df_agg):
    """Merge con lo storico giocatori aggregato tramite match fuzzy dei nomi."""
    hist_names = set(df_agg["player_name"])
    name_map = {}

    for p_name in df["player"]:
        if p_name in hist_names:
            name_map[p_name] = p_name
        elif p_name in config.MANUAL_FUZZY_MAP:
            mapped = config.MANUAL_FUZZY_MAP[p_name]
            name_map[p_name] = mapped if (mapped and mapped in hist_names) else None
        else:
            matches = difflib.get_close_matches(p_name, hist_names, n=1, cutoff=0.85)
            name_map[p_name] = matches[0] if matches else None

    df["storico_name"] = df["player"].map(name_map)
    matched = sum(1 for v in name_map.values() if v)
    print(f"  Match con storico: {matched} / {len(df)}")

    hist_cols = ["player_name", "n_stagioni", "mv_media_3y", "mv_storica",
                 "mv_std", "mv_trend", "availability",
                 "gol_per_pg", "ass_per_pg", "amm_per_pg", "rig_per_pg"]
    df_hist = df_agg[hist_cols].rename(columns={"player_name": "storico_name"})
    df = df.merge(df_hist, on="storico_name", how="left")
    df.drop(columns=["storico_name"], inplace=True, errors="ignore")
    return df


def merge_understat(df, df_us_agg):
    """Merge con Understat xG/xA tramite match cognome + fuzzy normalizzato."""
    us_names = df_us_agg["player_name_us"].tolist()
    us_norm  = [normalize(n) for n in us_names]

    # Build surname index: surname_norm → [(full_name, full_norm), ...]
    # Understat uses full names like "Donyell Malen", our dataset uses "Malen"
    surname_index = {}
    for i, full_name in enumerate(us_names):
        parts = full_name.strip().split()
        if parts:
            surname = normalize(parts[-1])
            surname_index.setdefault(surname, []).append((full_name, us_norm[i]))

    # Also build team-based index from Understat for disambiguation
    us_teams = {}
    if "team_us_last" in df_us_agg.columns:
        for _, row in df_us_agg.iterrows():
            us_teams[row["player_name_us"]] = normalize(str(row.get("team_us_last", "")))

    us_map = {}

    for fc_name in df["player"].unique():
        fc_norm = normalize(fc_name)
        # Remove trailing initials like "T." from "Chalobah T."
        fc_base = re.sub(r'\s+[a-z]{1,2}\.$', '', fc_norm).strip()

        # Strategy 1: Direct surname match
        fc_surname = fc_base.split()[-1] if fc_base.split() else fc_base
        if fc_surname in surname_index:
            candidates = surname_index[fc_surname]
            if len(candidates) == 1:
                # Unique surname match
                us_map[fc_name] = candidates[0][0]
                continue
            else:
                # Multiple candidates — try to narrow down by first name or team
                best = None
                for full_name, full_norm in candidates:
                    if fc_base in full_norm or full_norm.endswith(fc_base):
                        best = full_name
                        break
                if best:
                    us_map[fc_name] = best
                    continue
                # Take the first match as fallback (most recent)
                us_map[fc_name] = candidates[0][0]
                continue

        # Strategy 2: Full fuzzy match (lower cutoff)
        candidates = difflib.get_close_matches(fc_base, us_norm, n=1, cutoff=0.65)
        if candidates:
            idx = us_norm.index(candidates[0])
            us_map[fc_name] = us_names[idx]
            continue

        # Strategy 3: Try matching just surname against full names
        surname_fuzzy = difflib.get_close_matches(fc_surname, us_norm, n=1, cutoff=0.75)
        if surname_fuzzy:
            idx = us_norm.index(surname_fuzzy[0])
            us_map[fc_name] = us_names[idx]

    df["us_name"] = df["player"].map(us_map)
    matched_us = df["us_name"].notna().sum()
    print(f"  Match Understat: {matched_us} / {len(df)}")

    df = df.merge(
        df_us_agg.rename(columns={"player_name_us": "us_name"}),
        on="us_name", how="left"
    )
    df.drop(columns=["us_name", "team_us_last"], inplace=True, errors="ignore")
    return df


def apply_injuries(df):
    """Applica i dati infortuni dalla cache Transfermarkt."""
    if not os.path.exists(config.INJURIES_CACHE_JSON):
        print("  ⚠️  Cache infortuni non trovata, skip malus.")
        df["giorni_infortunio_3y"] = 0
        df["n_infortuni_3y"] = 0
        df["infortunio_grave"] = 0
        df["malus_infortuni"] = 0.0
        return df

    with open(config.INJURIES_CACHE_JSON, "r", encoding="utf-8") as f:
        cache = json.load(f)
    print(f"  Cache infortuni: {len(cache)} giocatori")

    giorni_list, n_inj_list, grave_list, malus_list = [], [], [], []

    for _, row in df.iterrows():
        p_name = str(row["player"]).strip()
        info = cache.get(p_name, {})

        giorni = info.get("giorni_infortunio_3y", 0)
        n_inj  = info.get("n_infortuni_3y", 0)
        grave  = info.get("infortunio_grave", 0)

        giorni_penalty = min(giorni / config.INJURY_DAYS_DENOMINATOR, 1.0)
        grave_penalty  = config.INJURY_GRAVE_PENALTY if grave else 0.0
        malus = min(giorni_penalty * 0.70 + grave_penalty, 1.0)

        giorni_list.append(giorni)
        n_inj_list.append(n_inj)
        grave_list.append(grave)
        malus_list.append(round(malus, 3))

    df["giorni_infortunio_3y"] = giorni_list
    df["n_infortuni_3y"]       = n_inj_list
    df["infortunio_grave"]     = grave_list
    df["malus_infortuni"]      = malus_list
    return df


def merge_lineups(df):
    """Merge con i dati delle formazioni reali 2026/27 (da Sofascore)."""
    lineup_path = config.FORMAZIONI_CSV
    if not os.path.exists(lineup_path):
        print("  ⚠️  Formazioni 2626/27 non trovate, skip titolari confermati.")
        df["starts_2627"] = 0
        df["sub_apps_2627"] = 0
        df["minutes_2627"] = 0
        df["is_starter_2627"] = False
        df["starter_pct_2627"] = 0.0
        return df

    df_lineups = pd.read_csv(lineup_path)
    print(f"  Formazioni caricate: {len(df_lineups)} giocatori")

    # Match via player_dataset column (already fuzzy-matched in stage 4b)
    if "player_dataset" not in df_lineups.columns:
        print("  ⚠️  Colonna player_dataset mancante, skip.")
        df["starts_2627"] = 0
        df["sub_apps_2627"] = 0
        df["minutes_2627"] = 0
        df["is_starter_2627"] = False
        df["starter_pct_2627"] = 0.0
        return df

    lineup_cols = ["player_dataset", "starts_2627", "sub_apps_2627",
                   "minutes_2627", "is_starter_2627", "starter_pct_2627"]
    df_lu = df_lineups[df_lineups["player_dataset"].notna()][lineup_cols].copy()
    df_lu = df_lu.rename(columns={"player_dataset": "player"})

    # Deduplicate: when multiple Sofascore players match the same dataset name
    # (e.g. "Di Lorenzo" matched to both Giovanni Di Lorenzo and Lorenzo Lucca),
    # keep the row with the most starts (the correct match)
    df_lu = df_lu.sort_values("starts_2627", ascending=False).drop_duplicates(
        subset=["player"], keep="first"
    )

    # Drop existing columns if re-running
    for c in ["starts_2627", "sub_apps_2627", "minutes_2627", "is_starter_2627", "starter_pct_2627"]:
        if c in df.columns:
            df.drop(columns=[c], inplace=True)

    df = df.merge(df_lu, on="player", how="left")

    # Fill missing with defaults
    df["starts_2627"] = df["starts_2627"].fillna(0).astype(int)
    df["sub_apps_2627"] = df["sub_apps_2627"].fillna(0).astype(int)
    df["minutes_2627"] = df["minutes_2627"].fillna(0).astype(int)
    df["is_starter_2627"] = df["is_starter_2627"].fillna(False).astype(bool)
    df["starter_pct_2627"] = df["starter_pct_2627"].fillna(0.0)

    starters = df["is_starter_2627"].sum()
    print(f"  Titolari confermati nel dataset: {starters} / {len(df)}")

    return df


def get_series(df: pd.DataFrame, col: str, default_val=0.0) -> pd.Series:
    """Safely extracts a numeric Series from df, avoiding AttributeError on missing columns."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default_val)
    return pd.Series(default_val, index=df.index, dtype=float)


def compute_score(df):
    """
    Calcola lo score composito.
    Formula pesata che combina: MV storica, MV attesa, FV attesa,
    probabilità bonus, xG, disponibilità, e prezzo (inversamente).
    """
    w = config.SCORE_WEIGHTS

    mv_base    = get_series(df, "mv_media_3y", np.nan).fillna(get_series(df, "NN_MV_Atteso", 0.0))
    xg_base    = get_series(df, "xg_media_3y", 0.0)
    avail_base = get_series(df, "availability", 0.75)

    df["score_composito"] = (
        w["mv_storica"]     * safe_norm(mv_base) +
        w["mv_attesa"]      * safe_norm(df["NN_MV_Atteso"]) +
        w["fv_attesa"]      * safe_norm(df["NN_FV_Atteso"]) +
        w["prob_bonus"]     * safe_norm(df["Prob_Bonus_Ge_8_%"]) +
        w["xg"]             * safe_norm(xg_base) +
        w["availability"]   * safe_norm(avail_base) +
        w["prezzo_inverso"] * (1 - safe_norm(df["Prezzo_Consigliato_Cr"]))
    ).round(4)

    # Salva score base prima del malus infortuni
    df["score_composito_base"] = df["score_composito"]

    # Applica malus infortuni (fino a -15%)
    df["score_composito"] = (
        df["score_composito_base"] * (1.0 - config.INJURY_MALUS_MAX_IMPACT * df["malus_infortuni"])
    ).round(4)

    return df


def main():
    """Esegue Fase 4: merge completo e calcolo score."""
    print("=" * 60)
    print("  FASE 4 — BUILD DATASET FINALE")
    print("=" * 60)

    # 1. Costruisci listone base (escludendo esplicitamente i ceduti)
    df_tutti, ceduti = load_quotazioni()
    df = build_listone(df_tutti, ceduti_names=ceduti)
    print(f"\n  Listone attivo (esclusi {len(ceduti)} ceduti): {len(df)} giocatori")

    # 2. Merge storico
    if os.path.exists(config.STORICO_AGG_CSV):
        df_agg = pd.read_csv(config.STORICO_AGG_CSV)
        df = merge_storico(df, df_agg)

    # 3. Merge Understat
    if os.path.exists(config.UNDERSTAT_AGG_CSV):
        df_us_agg = pd.read_csv(config.UNDERSTAT_AGG_CSV)
        df = merge_understat(df, df_us_agg)

    # 4. Merge indici squadra
    if os.path.exists(config.SQUADRE_AGG_CSV):
        df_sq = pd.read_csv(config.SQUADRE_AGG_CSV)
        df = df.merge(df_sq[["team", "offensive_index", "gf_avg_3y"]], on="team", how="left")
        print(f"  Match squadre: {df['offensive_index'].notna().sum()} / {len(df)}")

    # 5. Applica infortuni
    df = apply_injuries(df)

    # 5b. Merge formazioni reali 2026/27 (titolari confermati)
    df = merge_lineups(df)

    # 6. Calcola score
    df = compute_score(df)
    df.sort_values("score_composito", ascending=False, inplace=True)

    # 7. Salva
    df.to_csv(config.DATASET_FINALE_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Dataset salvato: {config.DATASET_FINALE_CSV} ({len(df)} giocatori)")

    # Report infortuni
    inj_cols = ["player", "role", "team", "Prezzo_Consigliato_Cr",
                "giorni_infortunio_3y", "n_infortuni_3y", "infortunio_grave",
                "malus_infortuni", "score_composito_base", "score_composito"]
    df[inj_cols].to_csv(config.INJURIES_CSV, index=False, encoding="utf-8-sig")

    # Riepilogo
    print(f"\n  Score medio: {df['score_composito'].mean():.4f}")
    print(f"  Score max:   {df['score_composito'].max():.4f}")

    for r_code, r_name in [('P','PORTIERI'), ('D','DIFENSORI'), ('C','CENTROCAMPISTI'), ('A','ATTACCANTI')]:
        sub = df[df['role'] == r_code].sort_values('score_composito', ascending=False).head(3)
        top_names = ", ".join(f"{r['player']} ({r['score_composito']:.4f})" for _, r in sub.iterrows())
        print(f"  {r_name}: {top_names}")

    print("\n  FASE 4 COMPLETATA.\n")


if __name__ == "__main__":
    main()
