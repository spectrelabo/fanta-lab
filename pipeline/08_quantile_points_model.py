#!/usr/bin/env python3
"""
STAGE 8 — Quantile Regression: Floor, Expected, and Ceiling Fantasy Points.

Trains multi-quantile gradient boosting models (P10 Floor, P50 Median, P90 Ceiling)
on multi-season historical player performance to predict total season fantasy points
with probabilistic uncertainty intervals.

Outputs added to data/dataset_finale.csv:
  - predicted_pts_p10: Conservative floor projection (10th percentile)
  - predicted_pts_p50: Expected median season points (50th percentile)
  - predicted_pts_p90: High-ceiling upside projection (90th percentile)
  - pts_volatility_spread: Upside vs downside spread (p90 - p10)
"""

import os, sys, warnings
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def build_historical_training_dataset():
    """
    Builds the historical training dataset from raw multi-season player statistics.
    Target: Total Season Fantasy Points = pg * mfv
    """
    raw_path = config.STORICO_RAW_CSV
    if not os.path.exists(raw_path):
        print(f"Warning: {raw_path} not found. Generating synthetic baseline.")
        return None, None

    df_raw = pd.read_csv(raw_path)

    # Filter records with meaningful activity
    df_train = df_raw[(df_raw["pg"] >= 5) & (df_raw["mfv"].notna()) & (df_raw["mv"].notna())].copy()

    # Target: Total Season Fantasy Points
    df_train["target_total_pts"] = (df_train["pg"] * df_train["mfv"]).round(1)

    # Historical feature engineering
    df_train["gol_rate"] = (df_train["gol"].fillna(0) / df_train["pg"]).round(3)
    df_train["ass_rate"] = (df_train["assist"].fillna(0) / df_train["pg"]).round(3)
    df_train["amm_rate"] = (df_train["amm"].fillna(0) / df_train["pg"]).round(3)
    df_train["avail_rate"] = (df_train["pg"] / 38.0).clip(upper=1.0).round(3)

    # Positional one-hot
    for r in ["P", "D", "C", "A"]:
        df_train[f"role_{r}"] = (df_train["role"] == r).astype(int)

    feature_cols = [
        "mv", "mfv", "gol_rate", "ass_rate", "amm_rate", "avail_rate",
        "role_P", "role_D", "role_C", "role_A"
    ]

    X = df_train[feature_cols].fillna(0)
    y = df_train["target_total_pts"]

    return X, y


def train_quantile_models(X, y):
    """
    Trains three Gradient Boosting Regressors for quantiles 0.10, 0.50, and 0.90.
    """
    print(f"  Training dataset: {len(X)} historical player-season records.")

    models = {}
    for alpha, name in [(0.10, "p10_floor"), (0.50, "p50_expected"), (0.90, "p90_ceiling")]:
        gbr = GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            n_estimators=120,
            max_depth=4,
            learning_rate=0.08,
            random_state=42
        )
        gbr.fit(X, y)
        models[name] = gbr
        print(f"  Trained {name} model (quantile={alpha:.2f})")

    return models


def predict_active_dataset(models, df_active):
    """
    Applies the trained quantile models to the active roster dataset.
    """
    df = df_active.copy()

    # Feature mapping for active dataset
    mv_input = pd.to_numeric(df.get("mv_media_3y"), errors="coerce").fillna(
        pd.to_numeric(df.get("NN_MV_Atteso"), errors="coerce").fillna(6.0)
    )
    mfv_input = pd.to_numeric(df.get("NN_FV_Atteso"), errors="coerce").fillna(mv_input)

    gol_rate = pd.to_numeric(df.get("gol_per_pg"), errors="coerce").fillna(0.0)
    ass_rate = pd.to_numeric(df.get("ass_per_pg"), errors="coerce").fillna(0.0)
    amm_rate = pd.to_numeric(df.get("amm_per_pg"), errors="coerce").fillna(0.15)
    avail_rate = pd.to_numeric(df.get("availability"), errors="coerce").fillna(0.75)

    # Adjust availability with medical injury malus
    injury_malus = pd.to_numeric(df.get("malus_infortuni"), errors="coerce").fillna(0.0)
    effective_avail = (avail_rate * (1.0 - 0.20 * injury_malus)).clip(0.1, 1.0)

    X_active = pd.DataFrame({
        "mv": mv_input,
        "mfv": mfv_input,
        "gol_rate": gol_rate,
        "ass_rate": ass_rate,
        "amm_rate": amm_rate,
        "avail_rate": effective_avail,
        "role_P": (df["role"] == "P").astype(int),
        "role_D": (df["role"] == "D").astype(int),
        "role_C": (df["role"] == "C").astype(int),
        "role_A": (df["role"] == "A").astype(int),
    })

    df["predicted_pts_p10"] = np.maximum(0, models["p10_floor"].predict(X_active).round(1))
    df["predicted_pts_p50"] = np.maximum(0, models["p50_expected"].predict(X_active).round(1))
    df["predicted_pts_p90"] = np.maximum(0, models["p90_ceiling"].predict(X_active).round(1))

    # Ensure monotonicity: p10 <= p50 <= p90
    df["predicted_pts_p50"] = np.maximum(df["predicted_pts_p50"], df["predicted_pts_p10"])
    df["predicted_pts_p90"] = np.maximum(df["predicted_pts_p90"], df["predicted_pts_p50"])
    df["pts_volatility_spread"] = (df["predicted_pts_p90"] - df["predicted_pts_p10"]).round(1)

    return df


def main():
    print("=" * 60)
    print("  STAGE 8 — QUANTILE REGRESSION (FLOOR / EXPECTED / CEILING)")
    print("=" * 60)

    if not os.path.exists(config.DATASET_FINALE_CSV):
        raise FileNotFoundError(f"Missing {config.DATASET_FINALE_CSV}. Run stage 06 first.")

    df_active = pd.read_csv(config.DATASET_FINALE_CSV)

    X_train, y_train = build_historical_training_dataset()
    if X_train is not None and len(X_train) > 100:
        models = train_quantile_models(X_train, y_train)
        df_updated = predict_active_dataset(models, df_active)
    else:
        print("  Using analytical quantile estimation fallback...")
        df_updated = df_active.copy()
        pts_base = df_updated["NN_FV_Atteso"].fillna(6.0) * (df_updated["availability"].fillna(0.75) * 38)
        df_updated["predicted_pts_p10"] = (pts_base * 0.75).round(1)
        df_updated["predicted_pts_p50"] = pts_base.round(1)
        df_updated["predicted_pts_p90"] = (pts_base * 1.30).round(1)
        df_updated["pts_volatility_spread"] = (df_updated["predicted_pts_p90"] - df_updated["predicted_pts_p10"]).round(1)

    df_updated.to_csv(config.DATASET_FINALE_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  Updated dataset with quantile projections: {config.DATASET_FINALE_CSV}")

    # Display Top 3 per role with Floor/Ceiling intervals
    print("\n  PROBABILISTIC FANTAPOINTS PROJECTIONS (P10 Floor | P50 Expected | P90 Ceiling):")
    for role, name in [("P", "Goalkeepers"), ("D", "Defenders"), ("C", "Midfielders"), ("A", "Forwards")]:
        sub = df_updated[df_updated["role"] == role].sort_values("predicted_pts_p50", ascending=False).head(4)
        print(f"\n  {name}:")
        for _, r in sub.iterrows():
            print(f"    {r['player']:<20} Sq:{str(r['team']):<4} "
                  f"Floor(P10): {r['predicted_pts_p10']:>5.1f} pts | "
                  f"Expected(P50): {r['predicted_pts_p50']:>5.1f} pts | "
                  f"Ceiling(P90): {r['predicted_pts_p90']:>5.1f} pts | "
                  f"Spread: {r['pts_volatility_spread']:>4.1f}")

    print("\n  STAGE 8 COMPLETED.\n")


if __name__ == "__main__":
    main()
