#!/usr/bin/env python3
"""
STAGE 10 — Mathematical 25-Player Roster & Budget Knapsack Optimizer (MILP).

Formulates and solves the multi-dimensional integer knapsack problem using
Mixed-Integer Linear Programming (MILP via scipy.optimize.milp) to construct the
theoretically optimal 25-player fantasy roster maximizing projected points under
strict budget and positional constraints.

Constraints:
  - Total Spend <= Budget (e.g., 500 or 1,000 credits)
  - Exactly 3 Goalkeepers (P)
  - Exactly 8 Defenders (D)
  - Exactly 8 Midfielders (C)
  - Exactly 6 Forwards (A)
  - Binary Decision: x_i in {0, 1}
"""

import os, sys, warnings
import pandas as pd
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def optimize_roster(df, budget=1000, price_col="Prezzo_Consigliato_Cr", locked_players=None):
    """
    Solves the 25-player roster optimization problem via MILP.
    
    Parameters:
      df: Master player dataset
      budget: Total credit budget limit (e.g. 500 or 1000)
      price_col: Column to use for player cost ('Prezzo_Consigliato_Cr' or 'prezzo_fair_1000')
      locked_players: List of player names already acquired (locked into roster)
    """
    df_opt = df.dropna(subset=["predicted_pts_p50", price_col]).reset_index(drop=True)
    n = len(df_opt)

    # Objective function: Maximize total expected points -> Minimize (-1 * expected_points)
    c = -1.0 * df_opt["predicted_pts_p50"].values

    # Price vector
    prices = df_opt[price_col].clip(lower=1).values

    # Position indicator matrices
    is_p = (df_opt["role"] == "P").astype(float).values
    is_d = (df_opt["role"] == "D").astype(float).values
    is_c = (df_opt["role"] == "C").astype(float).values
    is_a = (df_opt["role"] == "A").astype(float).values

    # Constraint matrix A
    # Row 0: Total cost <= budget
    # Row 1: Goalkeepers == 3
    # Row 2: Defenders == 8
    # Row 3: Midfielders == 8
    # Row 4: Forwards == 6
    A = np.vstack([prices, is_p, is_d, is_c, is_a])

    # Left-hand (lower) and Right-hand (upper) bounds for constraints
    lhs = np.array([0.0, 3.0, 8.0, 8.0, 6.0])
    rhs = np.array([float(budget), 3.0, 8.0, 8.0, 6.0])

    constraints = LinearConstraint(A, lhs, rhs)

    # Variable bounds: x_i in [0, 1]
    lower_bounds = np.zeros(n)
    upper_bounds = np.ones(n)

    # Lock in specific players if provided
    if locked_players:
        for name in locked_players:
            idx = df_opt[df_opt["player"] == name].index
            if len(idx) > 0:
                lower_bounds[idx[0]] = 1.0

    bounds = Bounds(lower_bounds, upper_bounds)

    # Integrality: 1 indicates integer (binary since bounds are [0, 1])
    integrality = np.ones(n)

    # Solve MILP
    res = milp(c=c, constraints=constraints, bounds=bounds, integrality=integrality)

    if not res.success:
        print(f"  Optimization failed: {res.status}")
        return None

    selected_indices = np.where(res.x > 0.5)[0]
    selected_roster = df_opt.iloc[selected_indices].copy()
    selected_roster["cost"] = prices[selected_indices]

    return selected_roster


def display_optimized_roster(roster, budget, price_col):
    """Prints a structured summary of the optimal roster."""
    total_spend = roster["cost"].sum()
    total_pts = roster["predicted_pts_p50"].sum()
    total_floor = roster["predicted_pts_p10"].sum()
    total_ceiling = roster["predicted_pts_p90"].sum()
    remaining_budget = budget - total_spend

    print(f"\n  OPTIMAL ROSTER SUMMARY (Budget: {budget} cr | Spend: {total_spend} cr | Bank: {remaining_budget} cr)")
    print(f"  Projected Points -> Expected: {total_pts:.1f} pts | Floor: {total_floor:.1f} pts | Ceiling: {total_ceiling:.1f} pts\n")

    for role, name, count in [("P", "Goalkeepers", 3), ("D", "Defenders", 8), ("C", "Midfielders", 8), ("A", "Forwards", 6)]:
        sub = roster[roster["role"] == role].sort_values("predicted_pts_p50", ascending=False)
        spend_role = sub["cost"].sum()
        pts_role = sub["predicted_pts_p50"].sum()
        print(f"  --- {name.upper()} ({len(sub)}/{count}) | Spend: {spend_role} cr | Projected: {pts_role:.1f} pts ---")
        for _, r in sub.iterrows():
            print(f"    {r['player']:<20} Sq:{str(r['team']):<4} Cost:{int(r['cost']):>3}cr | "
                  f"Exp:{r['predicted_pts_p50']:>5.1f} pts | Spread:{r['pts_volatility_spread']:>4.1f} | "
                  f"Score:{r['score_composito']:.4f}")
        print()


def main():
    print("=" * 60)
    print("  STAGE 10 — MATHEMATICAL ROSTER KNAPSACK OPTIMIZER (MILP)")
    print("=" * 60)

    if not os.path.exists(config.DATASET_FINALE_CSV):
        raise FileNotFoundError(f"Missing {config.DATASET_FINALE_CSV}.")

    df = pd.read_csv(config.DATASET_FINALE_CSV)

    if "predicted_pts_p50" not in df.columns:
        print("  Running prerequisite stages 08 and 09...")
        import importlib
        importlib.import_module("pipeline.08_quantile_points_model").main()
        importlib.import_module("pipeline.09_vorp_auction_pricing").main()
        df = pd.read_csv(config.DATASET_FINALE_CSV)

    # 1. Optimize on Official Quotations (Budget: 500)
    print("\n[Strategy A] Optimal 25-Player Roster on Official Prices (Budget: 500 Credits):")
    roster_500 = optimize_roster(df, budget=500, price_col="Prezzo_Consigliato_Cr")
    if roster_500 is not None:
        display_optimized_roster(roster_500, budget=500, price_col="Prezzo_Consigliato_Cr")

    # 2. Optimize on Fair Value (Budget: 1,000)
    print("\n[Strategy B] Optimal 25-Player Roster on Official Prices (Budget: 1,000 Credits):")
    roster_1000 = optimize_roster(df, budget=1000, price_col="Prezzo_Consigliato_Cr")
    if roster_1000 is not None:
        display_optimized_roster(roster_1000, budget=1000, price_col="Prezzo_Consigliato_Cr")

    print("  STAGE 10 COMPLETED.\n")


if __name__ == "__main__":
    main()
