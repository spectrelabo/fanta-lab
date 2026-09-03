#!/usr/bin/env python3
"""
FASE 1 — Raccolta dati storici giocatori e squadre Serie A.

Fonti:
  1. fantacalcio.it  → storico giocatori (MV, MFV, gol, assist...) per 11 stagioni
  2. football-data.co.uk → risultati Serie A per indici offensivi/difensivi squadra

Output:
  - storico_giocatori_raw.csv       (giocatore × stagione)
  - storico_giocatori_aggregato.csv  (media pesata multi-stagione)
  - storico_squadre_raw.csv          (squadra × stagione)
  - storico_squadre_aggregato.csv    (indici offensivi/difensivi)
"""

import os, sys, re, time, warnings
import requests
import pandas as pd
import numpy as np
from io import StringIO
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


# ──────────────────────────────────────────────────────────────────────
# PARTE 1 — FANTACALCIO.IT (storico giocatori)
# ──────────────────────────────────────────────────────────────────────

def get_cell(row, col_key):
    cell = row.find(attrs={"data-col-key": col_key})
    return cell.get_text(strip=True) if cell else None

def clean_float(s):
    if s is None or s.strip() in ("", "-", "N/D"):
        return None
    try:
        return float(s.replace(",", ".").strip())
    except ValueError:
        return None

def clean_int(s):
    if s is None or s.strip() in ("", "-", "N/D"):
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None

def scrape_fantacalcio_season(season):
    """Scarica le statistiche di una singola stagione da fantacalcio.it."""
    url = f"https://www.fantacalcio.it/statistiche-serie-a/{season}"
    print(f"  -> Scaricando {url} ...", end=" ", flush=True)
    try:
        resp = requests.get(url, headers=config.HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERRORE: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr.player-row")
    if not rows:
        print("ATTENZIONE: nessuna riga trovata.")
        return []

    records = []
    for row in rows:
        link_tag = row.select_one("a.player-link")
        if not link_tag:
            continue
        href = link_tag.get("href", "")
        pid_match = re.search(r"/(\d+)$", href)
        player_id = int(pid_match.group(1)) if pid_match else None

        name        = row.get("data-filter-keywords", "").strip()
        role        = row.get("data-filter-role-classic", "").strip()
        role_mantra = row.get("data-filter-role-mantra", "").strip()
        team_id     = row.get("data-filter-team-id", "").strip()
        team_abbr   = get_cell(row, "sq") or ""

        pg  = clean_int(get_cell(row, "pg"))
        mv  = clean_float(get_cell(row, "mv"))
        mfv = clean_float(get_cell(row, "mfv"))
        gol = clean_int(get_cell(row, "gol"))
        gs  = clean_int(get_cell(row, "gs"))
        ass = clean_int(get_cell(row, "ass"))
        amm = clean_int(get_cell(row, "amm"))
        esp = clean_int(get_cell(row, "esp"))
        rp  = clean_int(get_cell(row, "rp"))

        rig_raw = get_cell(row, "rig")
        rig_segnati, rig_tirati = None, None
        if rig_raw and "/" in rig_raw:
            parts = rig_raw.split("/")
            rig_segnati = clean_int(parts[0])
            rig_tirati  = clean_int(parts[1])

        if not name or mv is None:
            continue

        records.append({
            "player_id": player_id, "player_name": name,
            "role": role, "role_mantra": role_mantra,
            "team": team_abbr, "team_id_fc": team_id,
            "season": season,
            "pg": pg, "mv": mv, "mfv": mfv,
            "gol": gol, "gs": gs, "assist": ass,
            "amm": amm, "esp": esp, "rp": rp,
            "rig_segnati": rig_segnati, "rig_tirati": rig_tirati,
        })

    print(f"OK ({len(records)} giocatori)")
    return records


def scrape_all_fantacalcio():
    """Scarica tutte le stagioni da fantacalcio.it."""
    print("\n" + "=" * 60)
    print("FONTE 1 — fantacalcio.it (storico giocatori)")
    print("=" * 60)
    all_records = []
    for season in config.SEASONS_FC:
        records = scrape_fantacalcio_season(season)
        all_records.extend(records)
        time.sleep(config.RATE_LIMIT_SEC)
    df = pd.DataFrame(all_records)
    print(f"\n  Totale record: {len(df)}")
    print(f"  Stagioni: {df['season'].nunique()}")
    print(f"  Giocatori unici: {df['player_id'].nunique()}")
    return df


def aggregate_players(df_raw):
    """Aggrega le statistiche per giocatore su più stagioni con media pesata."""
    records = []
    for player_name, grp in df_raw.groupby("player_name"):
        grp = grp.sort_values("season", ascending=False).reset_index(drop=True)
        player_id   = grp.iloc[0]["player_id"]
        role        = grp.iloc[0]["role"]
        role_mantra = grp.iloc[0]["role_mantra"]
        n_stagioni  = len(grp)

        mvs = grp["mv"].dropna().tolist()
        n   = min(len(mvs), 3)
        if n > 0:
            weights     = list(range(n, 0, -1))
            mv_media_3y = sum(m * w for m, w in zip(mvs[:n], weights)) / sum(weights)
        else:
            mv_media_3y = None

        mv_storica = float(np.mean(mvs)) if mvs else None
        mv_std     = float(np.std(mvs))  if len(mvs) > 1 else 0.0

        if len(mvs) >= 3:
            x = np.arange(len(mvs) - 1, -1, -1)
            mv_trend = float(np.polyfit(x, mvs, 1)[0])
        else:
            mv_trend = None

        avail_list = [
            min(r["pg"] / 38.0, 1.0) for _, r in grp.iterrows()
            if pd.notna(r["pg"]) and r["pg"] > 0
        ]
        availability = float(np.mean(avail_list)) if avail_list else None

        grp_f  = grp[grp["pg"].fillna(0) > 10]
        pg_sum = grp_f["pg"].sum() if not grp_f.empty else 0

        def safe_rate(col):
            if grp_f.empty or pg_sum == 0:
                return None
            val = grp_f[col].fillna(0).sum()
            return round(float(val) / float(pg_sum), 3)

        records.append({
            "player_id":    int(player_id) if pd.notna(player_id) else 0,
            "player_name":  player_name,
            "role":         role,
            "role_mantra":  role_mantra,
            "n_stagioni":   n_stagioni,
            "mv_media_3y":  round(mv_media_3y, 3) if mv_media_3y else None,
            "mv_storica":   round(mv_storica,  3) if mv_storica  else None,
            "mv_std":       round(mv_std, 3),
            "mv_trend":     round(mv_trend, 4)    if mv_trend    else None,
            "availability": round(availability, 3) if availability else None,
            "gol_per_pg":   safe_rate("gol"),
            "ass_per_pg":   safe_rate("assist"),
            "amm_per_pg":   safe_rate("amm"),
            "rig_per_pg":   safe_rate("rig_segnati"),
        })

    df_agg = pd.DataFrame(records).sort_values("mv_media_3y", ascending=False, na_position="last")
    print(f"  Giocatori aggregati: {len(df_agg)}")
    return df_agg


# ──────────────────────────────────────────────────────────────────────
# PARTE 2 — FOOTBALL-DATA.CO.UK (storico squadre)
# ──────────────────────────────────────────────────────────────────────

def download_football_data_season(season, code):
    """Scarica i risultati di una stagione da football-data.co.uk."""
    url = f"https://www.football-data.co.uk/mmz4281/{code}/I1.csv"
    print(f"  -> Scaricando {url} ...", end=" ", flush=True)
    try:
        resp = requests.get(url, headers=config.HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERRORE: {e}")
        return None
    try:
        df = pd.read_csv(StringIO(resp.text), encoding="latin-1", on_bad_lines="skip")
    except Exception as e:
        print(f"ERRORE parsing: {e}")
        return None

    wanted = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HS", "AS", "HST", "AST"]
    available = [c for c in wanted if c in df.columns]
    df = df[available].dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df["season"] = season
    print(f"OK ({len(df)} partite)")
    return df


def build_team_indices(df_raw):
    """
    Costruisce indici offensivi/difensivi per squadra dalle statistiche
    dei giocatori di fantacalcio.it (fallback quando football-data è down).
    """
    print("\nCostruzione indici squadra...")

    top3 = sorted(df_raw["season"].unique(), reverse=True)[:3]
    df = df_raw[df_raw["season"].isin(top3)].copy()

    records = []
    for (season, team), grp in df.groupby(["season", "team"]):
        if not team or str(team).strip() == "":
            continue
        attackers = grp[grp["role"] != "P"]
        total_gol = attackers["gol"].fillna(0).sum()
        starters  = grp[grp["pg"].fillna(0) >= 15]
        n_games   = starters["pg"].mean() if not starters.empty else 30

        portieri = grp[grp["role"] == "P"].sort_values("pg", ascending=False)
        if not portieri.empty:
            top_por  = portieri.iloc[0]
            gs_total = top_por["gs"] if pd.notna(top_por["gs"]) else None
            pg_por   = top_por["pg"] if pd.notna(top_por["pg"]) and top_por["pg"] > 0 else n_games
        else:
            gs_total, pg_por = None, n_games

        gf_avg = round(float(total_gol) / float(n_games), 3) if n_games > 0 else None
        ga_avg = round(float(gs_total) / float(pg_por), 3) if gs_total is not None and pg_por > 0 else None

        records.append({
            "season": season, "team": team,
            "n_games": round(n_games, 0),
            "gf_avg": gf_avg, "ga_avg": ga_avg,
        })

    df_sq = pd.DataFrame(records)

    agg = (df_sq.groupby("team")
           .agg(gf_avg_3y=("gf_avg", "mean"),
                ga_avg_3y=("ga_avg", "mean"),
                n_stagioni=("season", "count"))
           .reset_index()
           .dropna(subset=["gf_avg_3y", "ga_avg_3y"]))

    def norm_to_mult(s, invert=False):
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series([1.0] * len(s), index=s.index)
        n = (s - mn) / (mx - mn)
        if invert:
            n = 1 - n
        return 0.90 + n * 0.20

    agg["offensive_index"] = norm_to_mult(agg["gf_avg_3y"]).round(4)
    agg["defensive_index"] = norm_to_mult(agg["ga_avg_3y"], invert=True).round(4)
    agg["gf_avg_3y"]       = agg["gf_avg_3y"].round(3)
    agg["ga_avg_3y"]       = agg["ga_avg_3y"].round(3)

    print(f"  Squadre con indici: {len(agg)}")
    return df_sq, agg.sort_values("offensive_index", ascending=False).reset_index(drop=True)


def main():
    """Esegue Fase 1: raccolta dati storici."""
    print("=" * 60)
    print("  FASE 1 — RACCOLTA DATI STORICI")
    print("=" * 60)

    df_players_raw = scrape_all_fantacalcio()
    df_players_raw.to_csv(config.STORICO_RAW_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  SALVATO: {config.STORICO_RAW_CSV}")

    print("\n  Aggregazione giocatori...")
    df_players_agg = aggregate_players(df_players_raw)
    df_players_agg.to_csv(config.STORICO_AGG_CSV, index=False, encoding="utf-8-sig")
    print(f"  SALVATO: {config.STORICO_AGG_CSV}")

    df_sq_raw, df_sq_idx = build_team_indices(df_players_raw)
    df_sq_raw.to_csv(config.SQUADRE_RAW_CSV, index=False, encoding="utf-8-sig")
    df_sq_idx.to_csv(config.SQUADRE_AGG_CSV, index=False, encoding="utf-8-sig")
    print(f"  SALVATO: {config.SQUADRE_RAW_CSV}")
    print(f"  SALVATO: {config.SQUADRE_AGG_CSV}")

    print("\n  FASE 1 COMPLETATA.\n")


if __name__ == "__main__":
    main()
