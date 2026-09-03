#!/usr/bin/env python3
"""
fanta-lab — Fine-Tuning Dataset Generator for Ollama / Qwen 2.5 3B.

Generates a specialized instruction-tuning dataset (JSONL) in ShareGPT / Alpaca format
based on quantitative Serie A fantasy football metrics (VORP, P10/P50/P90, Surplus Value).

Usage:
    python copilot/training_data/generate_finetune_dataset.py
    # Output: copilot/training_data/fanta_copilot_train.jsonl
"""

import os
import sys
import json
import random
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

DATA_PATH = os.path.join(BASE_DIR, "data", "dataset_finale.csv")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(BASE_DIR, "dataset_finale.csv")
if not os.path.exists(DATA_PATH):
    DATA_PATH = os.path.join(BASE_DIR, "examples", "dataset_sample.csv")

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fanta_copilot_train.jsonl")

SYSTEM_PROMPT = (
    "Sei FantaMoneyball AI, il consulente quantitativo senior per aste di Fantacalcio Serie A. "
    "Rispondi con rigore matematico basandoti su VORP, proiezioni quantile P10/P50/P90, "
    "prezzo fair a 500/1000 crediti e titolarità verificata. "
    "Usa un tono analitico, diretto, con una punta di cinismo statistico verso i giocatori 'hype' privi di valore."
)


def create_player_deepdive(row):
    p = row["player"]
    team = str(row.get("team", ""))
    role = row["role"]
    fair_1000 = int(row.get("prezzo_fair_1000", 1))
    fair_500 = int(row.get("prezzo_fair_500", 1))
    official = int(row.get("Prezzo_Consigliato_Cr", 1))
    p50 = float(row.get("predicted_pts_p50", 0))
    p10 = float(row.get("predicted_pts_p10", 0))
    p90 = float(row.get("predicted_pts_p90", 0))
    vorp = float(row.get("vorp_points", 0))
    surplus = int(row.get("surplus_value_cr", 0))
    inj_days = int(row.get("giorni_infortunio_3y", 0))
    starter = bool(row.get("is_starter_2627", False))

    questions = [
        f"Cosa ne pensi di {p} per la prossima asta?",
        f"Vale la pena prendere {p} del {team}?",
        f"Analisi quantitativa di {p}: fino a quanto posso rilanciare?",
        f"Scheda tecnica e prezzo consigliato per {p}."
    ]

    starter_str = "Titolare inamovibile" if starter else "Elemento di rotazione / ballottaggio aperto"
    surplus_str = f"sottovalutato (+{surplus} cr di surplus)" if surplus > 0 else f"sopravvalutato ({surplus} cr rispetto alla quotazione)"

    response = (
        f"### Analisi Tattica: **{p}** ({team} - {role})\n\n"
        f"- **Fair Price**: **{fair_1000} cr** (base 1000) / **{fair_500} cr** (base 500) [Listone ufficiale: {official} cr, {surplus_str}].\n"
        f"- **Proiezione Punti (Quantile ML)**: P50 Mediana: **{p50:.1f} pts** (Floor P10: {p10:.1f} | Ceiling P90: {p90:.1f} pts).\n"
        f"- **VORP (Value Over Replacement)**: **+{vorp:.1f} pts** sopra la linea di rimpiazzo dei svincolati.\n"
        f"- **Status Titolare**: {starter_str}.\n"
        f"- **Storico Infortuni (3y)**: {inj_days} giorni di assenza registrati.\n\n"
        f"**Verdetto d'asta**: Il target matematico è non superare mai {fair_1000} cr (o {fair_500} cr su scala 500). "
        + ("Profilo premium su cui puntare con convinzione." if vorp > 15 else "Buon tassello di reparto, da acquistare a prezzo di saldo.")
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": random.choice(questions)},
            {"role": "assistant", "content": response}
        ]
    }


def create_comparison(row1, row2):
    p1, p2 = row1["player"], row2["player"]
    v1, v2 = float(row1.get("vorp_points", 0)), float(row2.get("vorp_points", 0))
    f1_1000 = int(row1.get("prezzo_fair_1000", 1))
    f2_1000 = int(row2.get("prezzo_fair_1000", 1))
    p1_pts = float(row1.get("predicted_pts_p50", 0))
    p2_pts = float(row2.get("predicted_pts_p50", 0))

    winner = row1 if v1 >= v2 else row2
    loser = row2 if v1 >= v2 else row1

    questions = [
        f"Chi prendere tra {p1} e {p2}?",
        f"Meglio {p1} o {p2} all'asta?",
        f"Confronto {p1} vs {p2}: chi ha più valore statistico?"
    ]

    response = (
        f"### Confronto Diretto: **{p1}** vs **{p2}**\n\n"
        f"| Metrica | {p1} | {p2} |\n"
        f"| :--- | :--- | :--- |\n"
        f"| **Ruolo / Team** | {row1['role']} ({row1.get('team','')}) | {row2['role']} ({row2.get('team','')}) |\n"
        f"| **Punti Attesi (P50)** | **{p1_pts:.1f}** | **{p2_pts:.1f}** |\n"
        f"| **VORP Points** | **+{v1:.1f}** | **+{v2:.1f}** |\n"
        f"| **Fair Price (1000cr)** | {f1_1000} cr | {f2_1000} cr |\n\n"
        f"**Verdetto Analitico**: La scelta razionale è **{winner['player']}**. "
        f"Garantisce un delta di **+{abs(v1 - v2):.1f} punti VORP** rispetto al competitor, "
        f"offrendo maggiore rendimento netto per credito investito."
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": random.choice(questions)},
            {"role": "assistant", "content": response}
        ]
    }


def main():
    print(f"Loading dataset from: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    samples = []

    # 1. Deepdive per tutti i top 120 giocatori
    top_players = df.head(120)
    for _, row in top_players.iterrows():
        samples.append(create_player_deepdive(row))

    # 2. Confronti tra giocatori dello stesso ruolo
    for role in ["A", "C", "D", "P"]:
        role_df = df[df["role"] == role].head(30)
        role_records = role_df.to_dict(orient="records")
        for i in range(len(role_records) - 1):
            r1 = role_records[i]
            r2 = role_records[i + 1]
            samples.append(create_comparison(r1, r2))
            if i + 2 < len(role_records):
                samples.append(create_comparison(r1, role_records[i + 2]))

    # Shuffling
    random.shuffle(samples)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"✅ Generated {len(samples)} fine-tuning examples to: {OUT_PATH}")


if __name__ == "__main__":
    main()
