#!/usr/bin/env python3
"""
STAGE 8 — Quantile Regression Points Modeling (P10 Floor, P50 Expected, P90 Ceiling).

Trains Gradient Boosting Regressors on historical Serie A player-season performances
and projects probabilistic season fantasy points for all active players.
"""

import os, sys, warnings
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def prepare_training_data():
    """
    Loads historical seasons data and prepares feature matrix X and target y.
    Target: Total Season Fantasy Points = pg * mfv
    """
    raw_path = config.STORICO_RAW_CSV
    if not os.path.exists(raw_path):
        print(f"Warning: {raw_path} not found.")
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
            n_estimators=150,
            max_depth=4,
            learning_rate=0.06,
            random_state=42
        )
        gbr.fit(X, y)
        models[name] = gbr
        print(f"  Trained {name} model (quantile={alpha:.2f})")

    return models


def get_series(df: pd.DataFrame, col: str, default_val=0.0) -> pd.Series:
    """Safely extracts a numeric Series from df, avoiding AttributeError on missing columns."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default_val)
    return pd.Series(default_val, index=df.index, dtype=float)


def predict_active_dataset(models, df_active):
    """
    Applies the trained quantile models to the active roster dataset.
    """
    df = df_active.copy()

    # Handle new transfers from abroad & low historical Serie A sample sizes
    fvm_arr = get_series(df, "FVM_1000", 10.0)
    prezzo_arr = get_series(df, "Prezzo_Consigliato_Cr", 1.0)
    
    # 1. Base Mean Vote (MV)
    mv_input = pd.to_numeric(df["mv_media_3y"], errors="coerce") if "mv_media_3y" in df.columns else pd.Series(np.nan, index=df.index)
    mv_fallback = get_series(df, "NN_MV_Atteso", 6.05)
    mv_input = np.where(mv_input.isna() | ((mv_input < 5.6) & (fvm_arr >= 40)), mv_fallback, mv_input)
    mv_input = pd.Series(mv_input, index=df.index).fillna(6.05).clip(5.5, 7.0)

    # 2. Availability (use real lineup data + high FVM/price fallback)
    avail_rate = get_series(df, "availability", 0.75)
    is_starter = df["is_starter_2627"].fillna(False).astype(bool) if "is_starter_2627" in df.columns else pd.Series(False, index=df.index)
    starter_pct = get_series(df, "starter_pct_2627", 0.0)

    # Confirmed starters from real lineups: availability >= 0.82 (31+ matches/38)
    # Scale based on starter percentage: 100% starter → 0.88, 50% starter → 0.82
    starter_avail_floor = np.where(
        is_starter,
        np.clip(0.82 + starter_pct * 0.08, 0.82, 0.90),
        0.0
    )
    avail_rate = np.maximum(avail_rate, starter_avail_floor)

    # Fallback for high-value players without lineup data
    avail_rate = np.where(
        (fvm_arr >= 40) | (prezzo_arr >= 12),
        np.maximum(avail_rate, 0.80),
        avail_rate
    )
    avail_rate = pd.Series(avail_rate, index=df.index).clip(0.15, 1.0)

    # 3. Gol & Assist rates
    gol_rate = get_series(df, "gol_per_pg", 0.0)
    ass_rate = get_series(df, "ass_per_pg", 0.0)
    amm_rate = get_series(df, "amm_per_pg", 0.12)

    # Impute expected goal rate for foreign/new top strikers and midfielders
    for i in range(len(df)):
        r = df.iloc[i]["role"]
        f_val = fvm_arr.iloc[i]
        if r == "A" and gol_rate.iloc[i] < 0.10 and f_val >= 90:
            gol_rate.iloc[i] = round(0.15 + (f_val / 1000.0) * 1.05, 3)
            if ass_rate.iloc[i] < 0.05:
                ass_rate.iloc[i] = round(0.06 + (f_val / 1000.0) * 0.25, 3)
        elif r == "C" and gol_rate.iloc[i] < 0.05 and f_val >= 90:
            gol_rate.iloc[i] = round(0.08 + (f_val / 1000.0) * 0.50, 3)
            if ass_rate.iloc[i] < 0.05:
                ass_rate.iloc[i] = round(0.08 + (f_val / 1000.0) * 0.40, 3)

    # Compute genuine expected Fantamedia (MFV)
    mfv_input = (mv_input + (gol_rate * 3.0) + (ass_rate * 1.0) - (amm_rate * 0.5)).clip(5.0, 9.5)

    # Adjust availability with medical injury malus
    injury_malus = get_series(df, "malus_infortuni", 0.0)
    effective_avail = (avail_rate * (1.0 - 0.15 * injury_malus)).clip(0.15, 1.0)

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
        raise FileNotFoundError(f"Missing {config.DATASET_FINALE_CSV}.")

    X, y = prepare_training_data()
    if X is None or len(X) == 0:
        print("  Error: No training data available.")
        return

    models = train_quantile_models(X, y)

    df_active = pd.read_csv(config.DATASET_FINALE_CSV)
    df_predicted = predict_active_dataset(models, df_active)

    df_predicted.to_csv(config.DATASET_FINALE_CSV, index=False, encoding="utf-8-sig")
    print(f"\n  Updated dataset with quantile projections: {config.DATASET_FINALE_CSV}")

    print("\n  TOP ATTACKERS QUANTILE PROJECTIONS (P10 / P50 / P90):")
    top_a = df_predicted[df_predicted["role"] == "A"].sort_values("predicted_pts_p50", ascending=False).head(8)
    for _, r in top_a.iterrows():
        print(f"    {r['player']:<20} Sq:{str(r['team']):<4} "
              f"Floor(P10):{r['predicted_pts_p10']:>5.1f} | Expected(P50):{r['predicted_pts_p50']:>5.1f} | "
              f"Ceiling(P90):{r['predicted_pts_p90']:>5.1f} | Spread: {r['pts_volatility_spread']:>4.1f} pts")

    print("\n  STAGE 8 COMPLETED.\n")


if __name__ == "__main__":
    main()
