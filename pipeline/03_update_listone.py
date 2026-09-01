#!/usr/bin/env python3
"""
FASE 2 — Aggiornamento listone dal file Quotazioni ufficiale.

Legge il file Excel delle quotazioni Fantacalcio (scaricato da fantacalcio.it),
estrae la lista completa dei giocatori attivi e dei ceduti, e costruisce
il listone base con le informazioni ufficiali.

Input:
  - data/Quotazioni_Fantacalcio_Stagione_XXXX_XX_latest.xlsx

Output:
  - Listone base in memoria (usato da 06_build_dataset.py)
"""

import os, sys, warnings
import openpyxl
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def load_quotazioni():
    """
    Legge il file Quotazioni ufficiale e restituisce:
    - df_tutti: DataFrame di tutti i giocatori attivi
    - ceduti_names: set di nomi dei giocatori ceduti
    """
    if not os.path.exists(config.QUOTAZIONI_PATH):
        raise FileNotFoundError(
            f"File quotazioni non trovato: {config.QUOTAZIONI_PATH}\n"
            f"Scaricalo da fantacalcio.it e copialo in data/"
        )

    wb = openpyxl.load_workbook(config.QUOTAZIONI_PATH)

    data_tutti = list(wb['Tutti'].values)
    df_tutti = pd.DataFrame(data_tutti[2:], columns=data_tutti[1])

    data_ceduti = list(wb['Ceduti'].values)
    df_ceduti = pd.DataFrame(data_ceduti[2:], columns=data_ceduti[1])
    ceduti_names = set(df_ceduti['Nome'].dropna().str.strip())

    return df_tutti, ceduti_names


def build_listone(df_tutti):
    """
    Costruisce il listone base dai dati del file Quotazioni.
    Ogni giocatore ha: nome, ruolo, squadra, prezzo, FVM.
    """
    rows = []
    for _, r in df_tutti.iterrows():
        p_name = str(r['Nome']).strip() if pd.notna(r['Nome']) else ""
        if not p_name:
            continue

        role_classic = str(r['R']).strip() if pd.notna(r['R']) else ""
        role_mantra  = str(r['RM']).strip() if pd.notna(r['RM']) else ""
        team_full    = str(r['Squadra']).strip() if pd.notna(r['Squadra']) else ""
        team_abbr    = config.TEAM_ABBR_MAP.get(team_full, team_full[:3].upper())
        qta          = r['Qt.A'] if pd.notna(r.get('Qt.A')) else 1
        fvm          = r['FVM'] if pd.notna(r.get('FVM')) else 1

        rows.append({
            'player': p_name,
            'role': role_classic,
            'role_mantra': role_mantra,
            'team': team_abbr,
            'Prezzo_Consigliato_Cr': int(qta),
            'NN_FV_Atteso': float(fvm / 10.0) if fvm else 0.1,
            'NN_MV_Atteso': 6.00,
            'NN_Rischio_Std': 0.50,
            'Prob_Bonus_Ge_8_%': 0.0,
            'Prob_Picco_Ge_10_%': 0.0,
            'Clean_Sheet_%': 0.0,
            'FVM_1000': int(fvm) if fvm else 1,
        })

    return pd.DataFrame(rows)


def main():
    """Esegue Fase 2: costruzione listone da Quotazioni ufficiali."""
    print("=" * 60)
    print("  FASE 2 — AGGIORNAMENTO LISTONE")
    print("=" * 60)

    df_tutti, ceduti_names = load_quotazioni()
    print(f"\n  Giocatori in 'Tutti': {len(df_tutti)}")
    print(f"  Giocatori in 'Ceduti': {len(ceduti_names)}")

    df_listone = build_listone(df_tutti)
    print(f"  Listone costruito: {len(df_listone)} giocatori")

    # Riepilogo per ruolo
    for role, name in [("P", "Portieri"), ("D", "Difensori"), ("C", "Centrocampisti"), ("A", "Attaccanti")]:
        count = len(df_listone[df_listone["role"] == role])
        print(f"    {name}: {count}")

    print("\n  FASE 2 COMPLETATA.\n")
    return df_listone


if __name__ == "__main__":
    main()
