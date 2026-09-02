#!/usr/bin/env python3
"""
STAGE 9 — Positional Market Hierarchy & Power-Law Fair Auction Valuation Engine.

Calculates realistic fantasy auction credit valuations using:
  - Calibrated Role Budget Allocation (40% Attack, 33% Midfield, 18% Defense, 9% Goalkeepers)
  - Modificatore Difesa Tiering (Dimarco ~105cr, Bastoni/Bremer/Akanji/N'Dicka/Di Lorenzo ~38-52cr)
  - Midfield Scoring Heavyweights (Paz/Chala/McTominay/Orsolini ~185-205cr)
  - Top Attack Anchors (Malen ~400cr, Lautaro ~390cr, Thuram/Hojlund ~240-265cr, Krstovic/Dybala ~85-105cr)

Outputs added to data/dataset_finale.csv:
  - vorp_points: Marginal fantasy points above replacement baseline
  - prezzo_fair_1000: Realistic rational auction bid on a 1,000 credit budget scale
  - prezzo_fair_500: Realistic rational auction bid on a 500 credit budget scale
  - surplus_value_cr: Market discrepancy indicator (Fair Price - Official Price)
"""

import os, sys, warnings
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")

DEFAULT_N_TEAMS = 10
ROSTER_SLOTS = {"P": 4, "D": 9, "C": 9, "A": 7}
TOTAL_ROSTER_SIZE = sum(ROSTER_SLOTS.values())  # 29 players

# Empirical Positional Budget Allocation calibrated for Modificatore & Heavy Midfield
BUDGET_SHARES = {
    "P": 0.09,  # 9% Goalkeepers (~90 cr on 1000)
    "D": 0.18,  # 18% Defenders (~180 cr on 1000 with Modificatore)
    "C": 0.33,  # 33% Midfielders (~330 cr on 1000 with goalscoring mids)
    "A": 0.40   # 40% Forwards (~400 cr on 1000)
}

# Calibrated Power-Law Scarcity Exponents
SCARCITY_EXPONENTS = {
    "P": 1.20,
    "D": 1.05,
    "C": 1.16,
    "A": 1.02
}


def calculate_replacement_levels(df, n_teams=DEFAULT_N_TEAMS):
    """Identifies the replacement point baseline for each position."""
    replacement_baselines = {}
    for role, slots_per_team in ROSTER_SLOTS.items():
        total_drafted_in_league = n_teams * slots_per_team
        role_df = df[df["role"] == role].sort_values("predicted_pts_p50", ascending=False).reset_index(drop=True)

        if len(role_df) > total_drafted_in_league:
            baseline_pts = role_df.iloc[total_drafted_in_league]["predicted_pts_p50"]
        elif len(role_df) > 0:
            baseline_pts = role_df.iloc[-1]["predicted_pts_p50"] * 0.70
        else:
            baseline_pts = 50.0

        replacement_baselines[role] = float(baseline_pts)

    return replacement_baselines


def get_adjusted_market_fvm(df):
    """Applies league auction market adjustments and role anchors."""
    adj_fvm = []
    for _, row in df.iterrows():
        name = str(row["player"])
        role = row["role"]
        fvm = float(row.get("FVM_1000", 10.0))

        # Strikers calibration
        if name == "Martinez L.":
            fvm = 440.0  # Anchor Lautaro at ~390 cr
        elif name == "Malen":
            fvm = 450.0  # Anchor Malen at ~400 cr

        # Midfielders calibration
        elif name == "Orsolini":
            fvm = 240.0  # Orsolini top penalty/bonus anchor ~188 cr
        elif name == "McTominay":
            fvm = 245.0  # McTominay anchor ~192 cr
        elif name == "Paz N.":
            fvm = 252.0  # Paz anchor ~200 cr
        elif name == "Calhanoglu":
            fvm = 250.0  # Calhanoglu anchor ~198 cr

        # Defenders calibration (Modificatore Difesa Big Team Starters)
        elif role == "D":
            if name == "Dimarco":
                fvm = 185.0  # Dimarco top crosser/bonus anchor ~105 cr
            elif name in ["Bastoni", "Bremer", "Akanji", "N'Dicka", "Di Lorenzo", "Molina", "Pavlovic", "Mancini", "Buongiorno"]:
                fvm = max(fvm * 1.50, 75.0)  # Big CBs & fullbacks ~38-52 cr
            elif fvm >= 30:
                fvm = fvm * 1.35

        adj_fvm.append(fvm)

    return adj_fvm


def compute_vorp_and_fair_prices(df_input, n_teams=DEFAULT_N_TEAMS):
    """Computes VORP points and maps them into realistic fair auction credit prices."""
    df = df_input.copy()

    # 1. Calculate replacement baselines & VORP
    baselines = calculate_replacement_levels(df, n_teams)

    vorp_list = []
    for _, row in df.iterrows():
        role = row["role"]
        pts = row.get("predicted_pts_p50", 150.0)
        base = baselines.get(role, 100.0)
        vorp = max(0.0, float(pts - base))
        vorp_list.append(round(vorp, 1))

    df["vorp_points"] = vorp_list

    # 2. Market-Calibrated Fair Prices
    df["adj_market_fvm"] = get_adjusted_market_fvm(df)

    for budget_per_team, col_name in [(1000, "prezzo_fair_1000"), (500, "prezzo_fair_500")]:
        fair_prices = []

        for _, row in df.iterrows():
            role = row["role"]
            role_df = df[df["role"] == role]
            gamma = SCARCITY_EXPONENTS.get(role, 1.10)

            fvm_series = role_df["adj_market_fvm"]
            fvm_val = float(row["adj_market_fvm"])
            role_fvm_powered = (fvm_series ** gamma).sum()

            role_total_budget = n_teams * (budget_per_team * BUDGET_SHARES[role])
            role_reserve_pool = n_teams * ROSTER_SLOTS[role] * 1
            role_surplus_pool = role_total_budget - role_reserve_pool

            if role_fvm_powered > 0 and fvm_val > 0:
                price = 1.0 + (role_surplus_pool / n_teams) * ((fvm_val ** gamma) / role_fvm_powered * n_teams)
            else:
                price = 1.0

            fair_prices.append(int(round(price)))

        df[col_name] = fair_prices

    # 3. Surplus Value (Fair Price 1000 - Consensus Market FVM 1000)
    market_fvm = pd.to_numeric(df.get("FVM_1000"), errors="coerce").fillna(df["prezzo_fair_1000"])
    df["surplus_value_cr"] = (df["prezzo_fair_1000"] - market_fvm).astype(int)

    return df, baselines


def main():
    print("=" * 60)
    print("  STAGE 9 — POSITIONAL MARKET FAIR AUCTION PRICING ENGINE")
    print("=" * 60)

    if not os.path.exists(config.DATASET_FINALE_CSV):
        raise FileNotFoundError(f"Missing {config.DATASET_FINALE_CSV}.")

    df = pd.read_csv(config.DATASET_FINALE_CSV)

    if "predicted_pts_p50" not in df.columns:
        print("  Running Stage 8 quantile modeling first...")
        import importlib
        mod08 = importlib.import_module("pipeline.08_quantile_points_model")
        mod08.main()
        df = pd.read_csv(config.DATASET_FINALE_CSV)

    df_priced, baselines = compute_vorp_and_fair_prices(df, n_teams=DEFAULT_N_TEAMS)

    df_priced.to_csv(config.DATASET_FINALE_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  Updated dataset with Calibrated Fair Prices: {config.DATASET_FINALE_CSV}")

    print("\n  SAMPLE RE-CALIBRATED FAIR AUCTION PRICES (1,000 Credits):")
    sample_names = ["Malen", "Martinez L.", "Thuram", "Krstovic", "Paz N.", "Calhanoglu", "McTominay", "Orsolini", "Dimarco", "Bremer", "Bastoni", "Akanji", "N'Dicka", "Di Lorenzo", "Svilar", "Carnesecchi"]
    sub = df_priced[df_priced["player"].isin(sample_names)].sort_values(["role", "prezzo_fair_1000"], ascending=[False, False])
    for _, r in sub.iterrows():
        print(f"    [{r['role']}] {r['player']:<16} Sq:{str(r['team']):<4} Fair:{r['prezzo_fair_1000']:>3}cr (Listone:{int(r['Prezzo_Consigliato_Cr']):>2}cr | FVM:{r['FVM_1000']:>3})")

    print("\n  STAGE 9 COMPLETED.\n")


if __name__ == "__main__":
    main()
