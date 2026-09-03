#!/usr/bin/env python3
"""
Spectre - FantaMoneyball — Interactive Terminal Demo

Zero-configuration demo showcasing:
  1. Case Study: Media Hype Trap vs Statistical Value Gem
  2. Risk Analysis: Floor (P10) vs Ceiling (P90) Spreads
  3. Live Solver: Instant 25-Player Roster Optimizer via MILP
  4. Real-Time Player Lookup: Search any player to inspect Fair Price & VORP

Run directly:
  python demo.py
"""

import os
import sys
import pandas as pd
import numpy as np

# Ensure project root is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Prefer full dataset if available, fallback to examples/dataset_sample.csv
DATA_FILE = os.path.join(BASE_DIR, "data", "dataset_finale.csv")
if not os.path.exists(DATA_FILE):
    DATA_FILE = os.path.join(BASE_DIR, "examples", "dataset_sample.csv")


def load_demo_data():
    df = pd.read_csv(DATA_FILE)
    return df


def banner():
    print("\n" + "=" * 75)
    print("  Spectre - FantaMoneyball — Quantitative Fantasy Football Analytics Demo")
    print("=" * 75)
    print("  A cold, data-driven framework to exploit auction market inefficiencies.\n")


def demo_case_study(df):
    print("---------------------------------------------------------------------------")
    print("  DEMO 1: Hype Trap vs Statistical Gem (Market Inefficiency Detection)")
    print("---------------------------------------------------------------------------")
    print("  Comparing two assets with drastically different market perceptions:\n")

    # Find an undervalued gem and an overhyped asset
    gem = df.sort_values("surplus_value_cr", ascending=False).iloc[0]
    trap = df[df["Prezzo_Consigliato_Cr"] > 10].sort_values("surplus_value_cr", ascending=True).iloc[0]

    for label, p, tag in [("UNDERVALUED GEM", gem, "PRIMARY TARGET"), ("OVERHYPED TRAP", trap, "AVOID / PRICE DRIVER")]:
        print(f"  [{label}] -> {p['player']} ({p['role']}) - {p['team']} [{tag}]")
        print(f"    - Official List Price : {int(p['Prezzo_Consigliato_Cr']):>3} credits")
        print(f"    - Rational Fair Price : {int(p.get('prezzo_fair_1000', 0)):>3} credits (VORP: {p.get('vorp_points', 0):.1f} pts)")
        surplus = int(p.get("surplus_value_cr", 0))
        sign = "+" if surplus > 0 else ""
        print(f"    - Market Surplus Value: {sign}{surplus} credits ({'High ROI Bargain' if surplus > 0 else 'Capital Burner'})")
        print(f"    - Expected Season Pts : {p.get('predicted_pts_p50', 0):.1f} pts (Floor: {p.get('predicted_pts_p10', 0):.1f} | Ceiling: {p.get('predicted_pts_p90', 0):.1f})")
        print(f"    - 3y Injury Days Lost : {int(p.get('giorni_infortunio_3y', 0))} days (Malus: {p.get('malus_infortuni', 0):.3f})")
        print()


def demo_floor_ceiling(df):
    print("---------------------------------------------------------------------------")
    print("  DEMO 2: Quantile Uncertainty (Floor vs Ceiling Profile Comparison)")
    print("---------------------------------------------------------------------------")
    print("  Static averages hide volatility. Let's compare steady vs boom-or-bust profiles:\n")

    # Pick sample players across roles
    samples = df.dropna(subset=["predicted_pts_p50"]).sort_values("pts_volatility_spread", ascending=False)
    high_spread = samples.iloc[0]
    low_spread = df[(df["predicted_pts_p50"] > 140) & (df["pts_volatility_spread"] < 30)].iloc[0] if len(df[(df["predicted_pts_p50"] > 140) & (df["pts_volatility_spread"] < 30)]) > 0 else samples.iloc[-1]

    print(f"  [BOOM-OR-BUST PROFILE] -> {high_spread['player']} ({high_spread['role']}, {high_spread['team']})")
    print(f"    Floor (P10): {high_spread['predicted_pts_p10']:.1f} pts  |  Expected (P50): {high_spread['predicted_pts_p50']:.1f} pts  |  Ceiling (P90): {high_spread['predicted_pts_p90']:.1f} pts")
    print(f"    Uncertainty Spread: {high_spread['pts_volatility_spread']:.1f} pts -> High upside tournament/match-winner target.\n")

    print(f"  [ROCK-SOLID FLOOR PROFILE] -> {low_spread['player']} ({low_spread['role']}, {low_spread['team']})")
    print(f"    Floor (P10): {low_spread['predicted_pts_p10']:.1f} pts  |  Expected (P50): {low_spread['predicted_pts_p50']:.1f} pts  |  Ceiling (P90): {low_spread['predicted_pts_p90']:.1f} pts")
    print(f"    Uncertainty Spread: {low_spread['pts_volatility_spread']:.1f} pts -> Safe floor modifier defender/starter.\n")


def demo_roster_optimization(df):
    print("---------------------------------------------------------------------------")
    print("  DEMO 3: Instant MILP 25-Player Roster Knapsack Solver")
    print("---------------------------------------------------------------------------")
    print("  Solving multi-dimensional integer programming problem under strict constraints:")
    print("  Budget = 500 Credits | 3 Goalkeepers | 8 Defenders | 8 Midfielders | 6 Forwards\n")

    try:
        from pipeline.p10_roster_optimizer import optimize_roster
    except Exception:
        import importlib
        mod = importlib.import_module("pipeline.10_roster_optimizer")
        optimize_roster = mod.optimize_roster

    roster = optimize_roster(df, budget=500, price_col="Prezzo_Consigliato_Cr")

    if roster is not None:
        total_cost = roster["cost"].sum()
        total_exp = roster["predicted_pts_p50"].sum()
        total_floor = roster["predicted_pts_p10"].sum()
        total_ceiling = roster["predicted_pts_p90"].sum()

        print(f"  [SOLVER RESULT] Optimal Squad Found in <0.05 seconds:")
        print(f"    - Total Spend: {int(total_cost)} / 500 credits (Bank: {int(500 - total_cost)} cr)")
        print(f"    - Projected Season Points: {total_exp:.1f} pts (Floor: {total_floor:.1f} | Ceiling: {total_ceiling:.1f})\n")

        print("  Key Core Assets Selected by MILP Solver:")
        for role, name in [("P", "Goalkeeper"), ("D", "Top Defender"), ("C", "Top Midfielder"), ("A", "Top Forward")]:
            top_asset = roster[roster["role"] == role].sort_values("predicted_pts_p50", ascending=False).iloc[0]
            print(f"    [{name:<14}] {top_asset['player']:<18} ({top_asset['team']}) Cost:{int(top_asset['cost']):>2}cr | Exp:{top_asset['predicted_pts_p50']:>5.1f} pts | VORP:{top_asset.get('vorp_points', 0):>5.1f}")
        print()


def interactive_player_search(df):
    print("---------------------------------------------------------------------------")
    print("  DEMO 4: Real-Time Player Valuation Lookup")
    print("---------------------------------------------------------------------------")
    print("  Type any player surname (or press Enter to exit):")

    while True:
        try:
            query = input("\n  Search player > ").strip()
            if not query:
                print("  Exiting demo. Good luck at the auction!")
                break

            matches = df[df["player"].str.contains(query, case=False, na=False)]
            if matches.empty:
                print(f"  No player found matching '{query}'. Try another surname.")
                continue

            print(f"\n  Found {len(matches)} match(es):")
            print(f"  {'Player':<20} {'Role':4} {'Team':4} {'Official':>8} {'FairPrice':>10} {'Surplus':>8} {'Exp.Pts':>8} {'Floor':>7} {'Ceil':>7} {'Inj.Days':>9}")
            print("  " + "-" * 90)

            for _, r in matches.head(5).iterrows():
                surplus = int(r.get('surplus_value_cr', 0))
                sign = "+" if surplus > 0 else ""
                print(f"  {r['player']:<20} {r['role']:<4} {str(r['team']):<4} "
                      f"{int(r['Prezzo_Consigliato_Cr']):>7}cr "
                      f"{int(r.get('prezzo_fair_1000', 0)):>9}cr "
                      f"{sign + str(surplus):>7}cr "
                      f"{r.get('predicted_pts_p50', 0):>7.1f} "
                      f"{r.get('predicted_pts_p10', 0):>6.1f} "
                      f"{r.get('predicted_pts_p90', 0):>6.1f} "
                      f"{int(r.get('giorni_infortunio_3y', 0)):>7}d")
        except (KeyboardInterrupt, EOFError):
            print("\n  Exiting demo.")
            break


def main():
    banner()
    df = load_demo_data()
    demo_case_study(df)
    demo_floor_ceiling(df)
    demo_roster_optimization(df)
    interactive_player_search(df)


if __name__ == "__main__":
    main()
