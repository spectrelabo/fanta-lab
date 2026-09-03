#!/usr/bin/env python3
"""
FASE 2b — Scraping xG/xA da Understat.

Scarica le statistiche avanzate (Expected Goals, Expected Assists) da
Understat per le ultime stagioni di Serie A e le aggrega per giocatore.

Output:
  - understat_raw.csv        (giocatore × stagione)
  - understat_aggregato.csv  (media pesata multi-stagione)
"""

import os, sys, time, warnings
import requests
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def scrape_understat_season(season_year):
    """Scarica le statistiche di una stagione da Understat API."""
    url = "https://understat.com/main/getPlayersStats/"
    next_yr = str(int(season_year) + 1)[-2:]
    print(f"  -> Understat Serie A {season_year}/{next_yr} ...", end=" ", flush=True)
    try:
        resp = requests.post(url,
            data={"league": "Serie_A", "season": season_year},
            headers=config.HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"ERRORE: {e}")
        return []

    if not data.get("success"):
        print("ERRORE: success=False")
        return []

    records = []
    for p in data.get("players", []):
        try:
            records.append({
                "understat_id":   p.get("id"),
                "player_name_us": p.get("player_name", ""),
                "season_us":      season_year,
                "team_us":        p.get("team_title", ""),
                "games":          int(p.get("games", 0) or 0),
                "time_us":        int(p.get("time", 0) or 0),
                "goals_us":       int(p.get("goals", 0) or 0),
                "xg":             float(p.get("xG", 0) or 0),
                "assists_us":     int(p.get("assists", 0) or 0),
                "xa":             float(p.get("xA", 0) or 0),
                "shots":          int(p.get("shots", 0) or 0),
                "key_passes":     int(p.get("key_passes", 0) or 0),
                "npxg":           float(p.get("npxG", 0) or 0),
                "position_us":    p.get("position", ""),
            })
        except (ValueError, TypeError):
            continue

    print(f"OK ({len(records)} giocatori)")
    return records


def scrape_all_understat():
    """Scarica tutte le stagioni Understat configurate."""
    print("\n" + "=" * 60)
    print("FONTE — Understat.com API (xG/xA storico)")
    print("=" * 60)
    all_records = []
    for yr in config.UNDERSTAT_SEASONS:
        records = scrape_understat_season(yr)
        all_records.extend(records)
        time.sleep(config.RATE_LIMIT_SEC)
    df = pd.DataFrame(all_records)
    print(f"\n  Record totali: {len(df)}")
    return df


def aggregate_understat(df_us):
    """Aggrega xG/xA per giocatore con media pesata ultimi 3 anni."""
    if df_us.empty:
        return pd.DataFrame()

    records = []
    for name, grp in df_us.groupby("player_name_us"):
        grp = grp.sort_values("season_us", ascending=False).reset_index(drop=True)
        grp_ok = grp[grp["games"] >= 5]
        if grp_ok.empty:
            continue

        total_min = grp_ok["time_us"].sum()
        def per90(col):
            return round(float(grp_ok[col].sum()) / total_min * 90, 3) if total_min >= 270 else None

        xgs = grp_ok["xg"].tolist()
        n   = min(len(xgs), 3)
        w   = list(range(n, 0, -1))
        xg_3y = sum(x * ww for x, ww in zip(xgs[:n], w)) / sum(w) if n > 0 else None

        records.append({
            "player_name_us": name,
            "team_us_last":   grp.iloc[0]["team_us"],
            "n_seasons_us":   len(grp_ok),
            "xg_media_3y":    round(xg_3y, 3) if xg_3y else None,
            "xa_media_3y":    round(float(grp_ok["xa"].mean()), 3),
            "xg_per90":       per90("xg"),
            "xa_per90":       per90("xa"),
            "npxg_per90":     per90("npxg"),
            "shots_per90":    per90("shots"),
        })

    df_agg = pd.DataFrame(records)
    print(f"  Giocatori Understat aggregati: {len(df_agg)}")
    return df_agg


def main():
    """Esegue Fase 2b: scraping e aggregazione Understat."""
    print("=" * 60)
    print("  FASE 2b — UNDERSTAT xG/xA")
    print("=" * 60)

    df_us_raw = scrape_all_understat()
    if not df_us_raw.empty:
        df_us_raw.to_csv(config.UNDERSTAT_RAW_CSV, index=False, encoding="utf-8-sig")
        print(f"  SALVATO: {config.UNDERSTAT_RAW_CSV}")

    df_us_agg = aggregate_understat(df_us_raw)
    if not df_us_agg.empty:
        df_us_agg.to_csv(config.UNDERSTAT_AGG_CSV, index=False, encoding="utf-8-sig")
        print(f"  SALVATO: {config.UNDERSTAT_AGG_CSV}")

    print("\n  FASE 2b COMPLETATA.\n")


if __name__ == "__main__":
    main()
