#!/usr/bin/env python3
"""
STAGE 4b — Scraping formazioni reali Serie A 2026/27 da Sofascore.

Scarica le formazioni titolari dalle prime giornate di campionato
per identificare chi è davvero titolare e chi no.

Aggiunge al dataset:
  - starts_2627:        numero di volte che il giocatore è partito titolare
  - sub_apps_2627:      numero di volte che è entrato dalla panchina
  - minutes_2627:       minuti totali giocati
  - is_starter_2627:    True se ha iniziato almeno 1 partita dal 1'
  - starter_pct_2627:   % di partite in cui è partito titolare (starts / partite disputate dalla squadra)

Output:
  - data/formazioni_2627.csv
"""

import os, sys, time, warnings, unicodedata, re, difflib
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────────────
# SOFASCORE CONFIG
# ──────────────────────────────────────────────────────────────────────
SOFASCORE_BASE = "https://api.sofascore.com/api/v1"
SERIE_A_TOURNAMENT_ID = 23  # Serie A unique tournament ID on Sofascore

# How many matchdays to scrape (the first N rounds)
MAX_ROUNDS = 3

# Mapping Sofascore team names → 3-letter abbreviations used in our pipeline
SOFASCORE_TEAM_MAP = {
    "AS Roma": "ROM", "Roma": "ROM",
    "Inter": "INT", "Internazionale": "INT",
    "AC Milan": "MIL", "Milan": "MIL",
    "Juventus": "JUV",
    "SSC Napoli": "NAP", "Napoli": "NAP",
    "Atalanta": "ATA",
    "Lazio": "LAZ", "SS Lazio": "LAZ",
    "Fiorentina": "FIO", "ACF Fiorentina": "FIO",
    "Bologna": "BOL",
    "Torino": "TOR",
    "Udinese": "UDI",
    "Genoa": "GEN",
    "Cagliari": "CAG",
    "Parma": "PAR", "Parma Calcio 1913": "PAR",
    "Como": "COM", "Como 1907": "COM",
    "Monza": "MON",
    "Lecce": "LEC", "US Lecce": "LEC",
    "Venezia": "VEN", "Venezia FC": "VEN",
    "Sassuolo": "SAS", "US Sassuolo": "SAS",
    "Frosinone": "FRO",
    "Empoli": "EMP",
    "Verona": "VER", "Hellas Verona": "VER",
}

FORMAZIONI_CSV = os.path.join(config.DATA_DIR, "formazioni_2627.csv")


def normalize_name(s):
    """Normalize a player name: remove accents, lowercase, strip."""
    s = str(s).strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s.lower()


def get_sofascore_season_id():
    """Find the current Serie A season ID on Sofascore."""
    url = f"{SOFASCORE_BASE}/unique-tournament/{SERIE_A_TOURNAMENT_ID}/seasons"
    resp = requests.get(url, headers=config.HEADERS, timeout=15, verify=False)
    resp.raise_for_status()
    seasons = resp.json().get("seasons", [])
    if not seasons:
        raise ValueError("No seasons found for Serie A on Sofascore")
    # The first season in the list is the current one
    current = seasons[0]
    print(f"  Sofascore Season: {current.get('name', '?')} (id={current['id']})")
    return current["id"]


def get_round_events(season_id, round_num):
    """Get all match events for a specific round."""
    url = f"{SOFASCORE_BASE}/unique-tournament/{SERIE_A_TOURNAMENT_ID}/season/{season_id}/events/round/{round_num}"
    resp = requests.get(url, headers=config.HEADERS, timeout=15, verify=False)
    if resp.status_code != 200:
        return []
    events = resp.json().get("events", [])
    # Only return finished matches
    return [e for e in events if e.get("status", {}).get("type") == "finished"]


def get_match_lineups(event_id):
    """Get lineups for a specific match event."""
    url = f"{SOFASCORE_BASE}/event/{event_id}/lineups"
    resp = requests.get(url, headers=config.HEADERS, timeout=15, verify=False)
    if resp.status_code != 200:
        return None
    return resp.json()


def extract_players_from_lineup(lineup_data, team_key, team_name_sofascore, round_num):
    """Extract player records from a team's lineup data."""
    records = []
    team_data = lineup_data.get(team_key, {})
    players = team_data.get("players", [])
    team_abbr = SOFASCORE_TEAM_MAP.get(team_name_sofascore, "???")

    for p in players:
        player_info = p.get("player", {})
        name = player_info.get("name", "")
        short_name = player_info.get("shortName", name)
        position = p.get("position", "?")
        is_substitute = p.get("substitute", False)
        stats = p.get("statistics", {})
        minutes = stats.get("minutesPlayed", 0)

        records.append({
            "player_sofascore": name,
            "player_short": short_name,
            "team_sofascore": team_name_sofascore,
            "team": team_abbr,
            "position_sofascore": position,
            "is_starter": not is_substitute,
            "minutes_played": minutes,
            "round": round_num,
        })

    return records


def scrape_all_lineups():
    """Main scraping function: gets lineups for the first N matchdays."""
    print("  Connecting to Sofascore API...")
    season_id = get_sofascore_season_id()

    all_records = []

    for round_num in range(1, MAX_ROUNDS + 1):
        print(f"\n  === Giornata {round_num} ===")
        events = get_round_events(season_id, round_num)

        if not events:
            print(f"    No finished matches found for round {round_num}, stopping.")
            break

        for event in events:
            home_name = event.get("homeTeam", {}).get("name", "?")
            away_name = event.get("awayTeam", {}).get("name", "?")
            event_id = event["id"]
            home_score = event.get("homeScore", {}).get("current", "?")
            away_score = event.get("awayScore", {}).get("current", "?")

            print(f"    {home_name} {home_score}-{away_score} {away_name} (id={event_id})", end="")

            time.sleep(0.5)  # Rate limiting
            lineup_data = get_match_lineups(event_id)

            if not lineup_data:
                print(" — ⚠️ No lineup data")
                continue

            home_players = extract_players_from_lineup(lineup_data, "home", home_name, round_num)
            away_players = extract_players_from_lineup(lineup_data, "away", away_name, round_num)
            all_records.extend(home_players)
            all_records.extend(away_players)
            print(f" — ✅ {len(home_players)}+{len(away_players)} players")

    return pd.DataFrame(all_records)


def aggregate_player_stats(df_raw):
    """Aggregate per-match records into per-player season summaries."""
    if df_raw.empty:
        return pd.DataFrame()

    n_rounds = df_raw["round"].nunique()

    agg = df_raw.groupby(["player_sofascore", "team"]).agg(
        starts_2627=("is_starter", "sum"),
        sub_apps_2627=("is_starter", lambda x: (~x).sum()),
        minutes_2627=("minutes_played", "sum"),
        appearances=("round", "count"),
        position_sofascore=("position_sofascore", "first"),
    ).reset_index()

    agg["is_starter_2627"] = agg["starts_2627"] >= 1
    agg["starter_pct_2627"] = (agg["starts_2627"] / n_rounds).round(3)

    return agg


def match_to_dataset(df_lineups, df_dataset):
    """
    Match Sofascore player names to our dataset player names using fuzzy matching.
    Returns the lineup DataFrame with an added 'player_dataset' column.
    """
    dataset_names = df_dataset["player"].tolist()
    dataset_teams = dict(zip(df_dataset["player"], df_dataset["team"]))
    dataset_norm = {normalize_name(n): n for n in dataset_names}

    matched = []
    unmatched = []

    for _, row in df_lineups.iterrows():
        sofa_name = row["player_sofascore"]
        sofa_team = row["team"]
        sofa_norm = normalize_name(sofa_name)

        # 1. Exact normalized match
        if sofa_norm in dataset_norm:
            matched.append(dataset_norm[sofa_norm])
            continue

        # 2. Try matching by last name + team
        sofa_parts = sofa_name.split()
        last_name = sofa_parts[-1] if sofa_parts else sofa_name

        # Filter candidates by same team for better matching
        team_candidates = [n for n in dataset_names if dataset_teams.get(n) == sofa_team]
        team_candidates_norm = [normalize_name(n) for n in team_candidates]

        # Try fuzzy match within same team
        fuzzy = difflib.get_close_matches(sofa_norm, team_candidates_norm, n=1, cutoff=0.60)
        if fuzzy:
            idx = team_candidates_norm.index(fuzzy[0])
            matched.append(team_candidates[idx])
            continue

        # 3. Try last name match within team
        last_fuzzy = difflib.get_close_matches(
            normalize_name(last_name), team_candidates_norm, n=1, cutoff=0.70
        )
        if last_fuzzy:
            idx = team_candidates_norm.index(last_fuzzy[0])
            matched.append(team_candidates[idx])
            continue

        # 4. Global fuzzy match (lower cutoff)
        all_norm = [normalize_name(n) for n in dataset_names]
        global_fuzzy = difflib.get_close_matches(sofa_norm, all_norm, n=1, cutoff=0.70)
        if global_fuzzy:
            idx = all_norm.index(global_fuzzy[0])
            matched.append(dataset_names[idx])
            continue

        # Unmatched
        matched.append(None)
        unmatched.append(f"{sofa_name} ({sofa_team})")

    df_lineups["player_dataset"] = matched

    if unmatched:
        unique_unmatched = sorted(set(unmatched))
        print(f"\n  ⚠️  {len(unique_unmatched)} unique players not matched to dataset:")
        for u in unique_unmatched[:20]:
            print(f"      - {u}")
        if len(unique_unmatched) > 20:
            print(f"      ... and {len(unique_unmatched) - 20} more")

    return df_lineups


def main():
    print("=" * 60)
    print("  STAGE 4b — SCRAPING FORMAZIONI REALI SERIE A 2026/27")
    print("=" * 60)

    # 1. Scrape lineups
    df_raw = scrape_all_lineups()

    if df_raw.empty:
        print("\n  ❌ No lineup data scraped.")
        return

    print(f"\n  Total raw player-match records: {len(df_raw)}")
    print(f"  Unique players: {df_raw['player_sofascore'].nunique()}")
    print(f"  Rounds scraped: {df_raw['round'].nunique()}")

    # 2. Aggregate
    df_agg = aggregate_player_stats(df_raw)

    # 3. Match to dataset if available
    if os.path.exists(config.DATASET_FINALE_CSV):
        df_dataset = pd.read_csv(config.DATASET_FINALE_CSV)
        df_agg = match_to_dataset(df_agg, df_dataset)

        matched_count = df_agg["player_dataset"].notna().sum()
        print(f"\n  Matched to dataset: {matched_count} / {len(df_agg)}")

    # 4. Save
    df_agg.to_csv(FORMAZIONI_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ Formazioni salvate: {FORMAZIONI_CSV}")

    # 5. Summary stats
    starters = df_agg[df_agg["is_starter_2627"]]
    print(f"\n  Titolari confermati (≥1 start): {len(starters)}")

    for team in sorted(df_agg["team"].unique()):
        team_starters = starters[starters["team"] == team]
        print(f"    {team}: {len(team_starters)} titolari")

    # Show some notable starters with low FVM that would be VORP-fixed
    if "player_dataset" in df_agg.columns and os.path.exists(config.DATASET_FINALE_CSV):
        df_dataset = pd.read_csv(config.DATASET_FINALE_CSV)
        vorp_zero = df_dataset[df_dataset.get("vorp_points", pd.Series(dtype=float)).fillna(0) == 0]

        if not vorp_zero.empty:
            fixed = df_agg[
                (df_agg["player_dataset"].isin(vorp_zero["player"])) &
                (df_agg["is_starter_2627"] == True)
            ]
            if not fixed.empty:
                print(f"\n  🔧 Titolari confermati che avevano VORP=0:")
                for _, r in fixed.iterrows():
                    print(f"      {r['player_dataset']:25s} ({r['team']}) "
                          f"starts={r['starts_2627']} min={r['minutes_2627']}")

    print("\n  STAGE 4b COMPLETED.\n")


if __name__ == "__main__":
    main()
