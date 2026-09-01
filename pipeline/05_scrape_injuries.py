#!/usr/bin/env python3
"""
FASE 3 — Scraping infortuni da Transfermarkt.

Per ogni giocatore nel dataset, cerca il profilo su Transfermarkt,
verifica la corrispondenza con la squadra, ed estrae lo storico
infortuni degli ultimi 3 anni. Calcola il malus fragilità.

Output:
  - tm_injuries_cache.json  (cache completa profili)
  - Aggiornamento colonne infortuni nel dataset finale
"""

import os, sys, re, time, json, warnings, urllib.parse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")

lock = threading.Lock()
cache = {}


def clean_query(name):
    """Pulisce iniziali tipo ' L.' o ' Jo.' per la ricerca su Transfermarkt."""
    q = re.sub(r'\s+[A-Z][a-z]?\.$', '', name).strip()
    return q


def fetch_player_injuries(row):
    """Cerca un giocatore su Transfermarkt e ne estrae lo storico infortuni."""
    player_name = str(row["player"]).strip()
    team_abbr   = str(row["team"]).strip() if pd.notna(row.get("team")) else ""
    team_tm     = config.TEAM_TM_MAP.get(team_abbr, "")

    q_name = clean_query(player_name)
    search_url = f"https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={urllib.parse.quote(q_name)}"

    result = {
        "player_name": player_name,
        "tm_found": False,
        "tm_matched_name": "",
        "giorni_infortunio_3y": 0,
        "n_infortuni_3y": 0,
        "infortunio_grave": 0,
        "max_giorni_singolo": 0,
        "dettaglio_infortuni": []
    }

    try:
        resp = requests.get(search_url, headers=config.HEADERS, timeout=8)
        if resp.ok:
            soup = BeautifulSoup(resp.text, "html.parser")
            player_rows = soup.select("div.box #yw1 tbody tr")
            if not player_rows:
                player_rows = soup.select("table.items tbody tr")

            target_href = None
            target_name = ""

            for pr in player_rows:
                a_link = pr.select_one('td.hauptlink a[href*="/profil/spieler/"]')
                if not a_link:
                    continue

                p_title = a_link.get_text(strip=True)
                p_href  = a_link["href"]

                club_img = pr.select_one("td.zentriert img[alt]")
                club_name = club_img["alt"] if club_img else ""

                if team_tm and team_tm.lower() in club_name.lower():
                    target_href = p_href
                    target_name = p_title
                    break
                elif not target_href:
                    target_href = p_href
                    target_name = p_title

            if target_href:
                injury_href = target_href.replace("/profil/spieler/", "/verletzungen/spieler/")
                injury_url  = "https://www.transfermarkt.com" + injury_href

                resp2 = requests.get(injury_url, headers=config.HEADERS, timeout=8)
                if resp2.ok:
                    soup2 = BeautifulSoup(resp2.text, "html.parser")
                    rows  = soup2.select("table.items tbody tr")

                    total_days, n_inj, max_days = 0, 0, 0
                    details = []

                    for r in rows:
                        tds = [td.get_text(strip=True) for td in r.find_all("td")]
                        if len(tds) >= 4:
                            season = tds[0]
                            reason = tds[1]
                            days_str = tds[4] if len(tds) > 4 else ""

                            m = re.search(r"(\d+)\s*days?", days_str)
                            days = int(m.group(1)) if m else 0

                            if any(s in season for s in config.INJURY_SEASONS_FILTER):
                                total_days += days
                                n_inj += 1
                                if days > max_days:
                                    max_days = days
                                details.append(f"{season}: {reason} ({days}d)")

                    result["tm_found"] = True
                    result["tm_matched_name"] = target_name
                    result["giorni_infortunio_3y"] = total_days
                    result["n_infortuni_3y"] = n_inj
                    result["max_giorni_singolo"] = max_days
                    result["infortunio_grave"] = 1 if max_days >= config.INJURY_GRAVE_THRESHOLD else 0
                    result["dettaglio_infortuni"] = details

    except Exception:
        pass

    with lock:
        cache[player_name] = result

    return player_name, result


def main():
    """Esegue Fase 3: scraping infortuni Transfermarkt."""
    print("=" * 60)
    print("  FASE 3 — SCRAPING INFORTUNI TRANSFERMARKT")
    print("=" * 60)

    df = pd.read_csv(config.DATASET_FINALE_CSV)
    rows_to_process = [r for _, r in df.iterrows()]

    print(f"\n  Giocatori da processare: {len(df)}")
    start_time = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=config.TM_MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_player_injuries, r): r["player"] for r in rows_to_process}
        for future in as_completed(futures):
            completed += 1
            if completed % 30 == 0 or completed == len(rows_to_process):
                with lock:
                    with open(config.INJURIES_CACHE_JSON, "w", encoding="utf-8") as f:
                        json.dump(cache, f, ensure_ascii=False, indent=2)
                elapsed = time.time() - start_time
                print(f"  Progresso: {completed} / {len(rows_to_process)} in {elapsed:.1f}s")

    # Salvataggio finale cache
    with open(config.INJURIES_CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    found_count = sum(1 for v in cache.values() if v.get("tm_found"))
    print(f"\n  ✅ Scraping completato in {time.time() - start_time:.1f}s")
    print(f"  Profili TM trovati: {found_count} / {len(cache)}")

    # Aggiorna DataFrame con dati infortuni
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

    # Ricalcola score con malus
    df["score_composito_base"] = df.get("score_composito_base", df["score_composito"])
    df["score_composito"] = (
        df["score_composito_base"] * (1.0 - config.INJURY_MALUS_MAX_IMPACT * df["malus_infortuni"])
    ).round(4)

    df.sort_values("score_composito", ascending=False, inplace=True)
    df.to_csv(config.DATASET_FINALE_CSV, index=False, encoding="utf-8-sig")

    # Report infortuni
    inj_cols = ["player", "role", "team", "Prezzo_Consigliato_Cr",
                "giorni_infortunio_3y", "n_infortuni_3y", "infortunio_grave",
                "malus_infortuni", "score_composito"]
    df[inj_cols].to_csv(config.INJURIES_CSV, index=False, encoding="utf-8-sig")

    print(f"  ✅ Dataset aggiornato: {config.DATASET_FINALE_CSV}")
    print(f"  ✅ Report infortuni: {config.INJURIES_CSV}")

    # Top fragili
    print(f"\n  TOP 10 GIOCATORI PIÙ FRAGILI:")
    top = df.sort_values("giorni_infortunio_3y", ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"    {r['player']:<22} {r['role']:<2} {str(r['team']):<4} "
              f"Giorni={r['giorni_infortunio_3y']:>4} Malus={r['malus_infortuni']:.3f}")

    print("\n  FASE 3 COMPLETATA.\n")


if __name__ == "__main__":
    main()
