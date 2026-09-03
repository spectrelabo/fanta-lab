#!/usr/bin/env python3
"""
Spectre - FantaMoneyball — Export & Calibration Dataset CLI
Consente di generare o esportare il dataset finale tarato su scala 500 crediti o 1000 crediti.

Uso:
  python export_dataset.py --budget 500
  python export_dataset.py --budget 1000
"""

import argparse
import os
import pandas as pd
import config


def export_budget_dataset(budget: int):
    master_path = config.DATASET_FINALE_CSV
    if not os.path.exists(master_path):
        print(f"Errore: Dataset master non trovato in {master_path}.")
        print("Esegui prima: python run_pipeline.py --step 9")
        return False

    df = pd.read_csv(master_path)
    col_name = f"prezzo_fair_{budget}"
    if col_name not in df.columns:
        print(f"Errore: Colonna '{col_name}' non presente nel dataset.")
        return False

    df_out = df.copy()
    df_out["prezzo_fair"] = df_out[col_name]

    out_file = os.path.join(config.DATA_DIR, f"dataset_finale_{budget}.csv")
    df_out.to_csv(out_file, index=False, encoding="utf-8-sig")

    print(f"\n{'='*65}")
    print(f"  DATASET CALIBRATO — {budget} CREDITI")
    print(f"{'='*65}")
    print(f"  File: {out_file}")
    print(f"  Totale Calciatori Attivi: {len(df_out)}")
    print("\n  Top 5 Calciatori per Fair Price:")
    top5 = df_out.sort_values(col_name, ascending=False).head(5)
    for _, r in top5.iterrows():
        print(f"    [{r['role']}] {r['player']:<18} ({r['team']}) -> Fair Price: {int(r[col_name])} cr (Listone: {int(r['Prezzo_Consigliato_Cr'])})")
    print(f"{'='*65}\n")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Esporta dataset finale calibrato su 500 o 1000 crediti")
    parser.add_argument("--budget", type=int, choices=[500, 1000], default=1000, help="Budget crediti lega (500 o 1000)")
    args = parser.parse_args()
    export_budget_dataset(args.budget)
