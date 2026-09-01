#!/usr/bin/env python3
"""
STAGE 9 — Value Over Replacement Player (VORP) & Fair Auction Valuation Engine.

Converts probabilistic point projections into mathematical fair-market credit valuations
using the sabermetric VORP (Value Over Replacement Player) principle.

Outputs added to data/dataset_finale.csv:
  - vorp_points: Marginal fantasy points above the waiver-wire replacement baseline
  - prezzo_fair_1000: Fair rational auction bid on a 1,000 credit budget scale
  - prezzo_fair_500: Fair rational auction bid on a 500 credit budget scale
  - surplus_value_cr: Market discrepancy indicator (Fair Price - Official Price)
"""

import os, sys, warnings
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")

# Standard Auction League Parameters
DEFAULT_N_TEAMS = 8
ROSTER_SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
TOTAL_ROSTER_SIZE = sum(ROSTER_SLOTS.values())  # 25 players


def calculate_replacement_levels(df, n_teams=DEFAULT_N_TEAMS):
    """
    Identifies the replacement point baseline for each position.
    Replacement level is the points of the (Total Drafted in League + 1)-th player.
    """
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


def compute_vorp_and_fair_prices(df_input, n_teams=DEFAULT_N_TEAMS):
    """
    Computes VORP points and maps them into fair monetary credit prices for budgets of 1000 and 500.
    """
    df = df_input.copy()

    # Calculate replacement baselines
    baselines = calculate_replacement_levels(df, n_teams)

    # Calculate VORP for each player
    vorp_list = []
    for _, row in df.iterrows():
        role = row["role"]
        pts = row.get("predicted_pts_p50", 150.0)
        base = baselines.get(role, 100.0)
        vorp = max(0.0, float(pts - base))
        vorp_list.append(round(vorp, 1))

    df["vorp_points"] = vorp_list

    # Total league draft slots and surplus pools
    total_league_slots = n_teams * TOTAL_ROSTER_SIZE
    total_vorp_pool = df["vorp_points"].sum()

    for budget_per_team, col_name in [(1000, "prezzo_fair_1000"), (500, "prezzo_fair_500")]:
        total_league_budget = n_teams * budget_per_team
        minimum_reserve_pool = total_league_slots * 1  # 1 credit minimum per slot
        surplus_budget_pool = total_league_budget - minimum_reserve_pool

        fair_prices = []
        for vorp in df["vorp_points"]:
            if total_vorp_pool > 0 and vorp > 0:
                price = 1.0 + surplus_budget_pool * (vorp / total_vorp_pool)
            else:
                price = 1.0
            fair_prices.append(int(round(price)))

        df[col_name] = fair_prices

    # Calculate surplus value (Fair Price 1000 - Official Price)
    official_price = pd.to_numeric(df.get("Prezzo_Consigliato_Cr"), errors="coerce").fillna(1)
    df["surplus_value_cr"] = (df["prezzo_fair_1000"] - official_price).astype(int)

    return df, baselines


def main():
    print("=" * 60)
    print("  STAGE 9 — VORP & FAIR AUCTION PRICING ENGINE")
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
    print(f"\n  Updated dataset with VORP and Fair Pricing: {config.DATASET_FINALE_CSV}")

    print("\n  POSITIONAL REPLACEMENT BASELINES (Waiver-Wire Cutoff):")
    for role, name in [("P", "Goalkeepers"), ("D", "Defenders"), ("C", "Midfielders"), ("A", "Forwards")]:
        print(f"    {name} ({role}): Baseline = {baselines[role]:.1f} projected season points")

    print("\n  TOP 5 VALUE PLAYS (Highest Positive Surplus Value / Undervalued Targets):")
    top_surplus = df_priced.sort_values("surplus_value_cr", ascending=False).head(5)
    for _, r in top_surplus.iterrows():
        print(f"    {r['player']:<20} ({r['role']}) Sq:{str(r['team']):<4} "
              f"Official:{int(r['Prezzo_Consigliato_Cr']):>3}cr -> Fair:{r['prezzo_fair_1000']:>3}cr "
              f"| Surplus: +{r['surplus_value_cr']:>3}cr (VORP: {r['vorp_points']:.1f} pts)")

    print("\n  TOP 5 OVERPRICED PLAYERS (Highest Negative Surplus Value / Overhyped Traps):")
    bottom_surplus = df_priced[df_priced["Prezzo_Consigliato_Cr"] > 5].sort_values("surplus_value_cr", ascending=True).head(5)
    for _, r in bottom_surplus.iterrows():
        print(f"    {r['player']:<20} ({r['role']}) Sq:{str(r['team']):<4} "
              f"Official:{int(r['Prezzo_Consigliato_Cr']):>3}cr -> Fair:{r['prezzo_fair_1000']:>3}cr "
              f"| Surplus: {r['surplus_value_cr']:>3}cr (VORP: {r['vorp_points']:.1f} pts)")

    print("\n  STAGE 9 COMPLETED.\n")


if __name__ == "__main__":
    main()
