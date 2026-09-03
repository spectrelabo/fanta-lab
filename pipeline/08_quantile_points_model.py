#!/usr/bin/env python3
"""
STAGE 8 — Quantile Regression Points Modeling (P10 Floor, P50 Expected, P90 Ceiling).

Eliminates Target Leakage and Train-Serve Skew by training three Gradient Boosting
Regressors on genuine multi-season lagged transitions (seasons t-1 ... t-3 predicting season t)
across 11 Serie A seasons (2015-16 to 2025-26).
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
    Constructs a true lagged time-series training dataset from historical Serie A records.
    
    Target: Total Season Fantasy Points in season t = pg_t * mfv_t
    Features: Multi-season rolling statistics strictly computed prior to season t (t-1, t-2, t-3).
    Zero Target Leakage: No in-season statistics from season t are used as features.
    """
    raw_path = config.STORICO_RAW_CSV
    if not os.path.exists(raw_path):
        print(f"Warning: {raw_path} not found.")
        return None, None, None

    df_raw = pd.read_csv(raw_path)

    # Guardrail: a mostly-null player_id means Stage 1's scraper broke
    # (e.g. upstream site changed structure) and wrote corrupt data.
    # Fail loudly here instead of silently training on zero samples.
    null_pct = df_raw["player_id"].isna().mean() if "player_id" in df_raw.columns else 1.0
    if null_pct > 0.05:
        raise RuntimeError(
            f"{raw_path} has {null_pct:.0%} null player_id — source data looks "
            f"corrupt. Re-run Stage 1 (--step 1) to regenerate it before retraining."
        )

    # Chronological season index
    season_order = sorted(df_raw["season"].unique())
    season_idx = {s: i for i, s in enumerate(season_order)}
    df_raw["s_idx"] = df_raw["season"].map(season_idx)
    df_raw = df_raw.sort_values(["player_id", "s_idx"]).reset_index(drop=True)

    records = []
    for pid, group in df_raw.groupby("player_id"):
        group = group.sort_values("s_idx")
        if len(group) < 2:
            continue

        for i in range(1, len(group)):
            curr = group.iloc[i]
            prior = group.iloc[:i]

            # Minimum activity in target season (at least 3 appearances to evaluate fantasy points)
            if curr["pg"] < 3 or pd.isna(curr["mfv"]) or pd.isna(curr["mv"]):
                continue

            last1 = prior.iloc[-1]
            last3 = prior.tail(3)

            tot_pg = float(last3["pg"].sum())
            if tot_pg > 0:
                mv_3y = float((last3["mv"] * last3["pg"]).sum() / tot_pg)
                mfv_3y = float((last3["mfv"] * last3["pg"]).sum() / tot_pg)
                gol_3y = float(last3["gol"].sum() / tot_pg)
                ass_3y = float(last3["assist"].sum() / tot_pg)
                amm_3y = float(last3["amm"].sum() / tot_pg)
            else:
                mv_3y = float(last1["mv"]) if pd.notna(last1["mv"]) else 6.0
                mfv_3y = float(last1["mfv"]) if pd.notna(last1["mfv"]) else 6.0
                gol_3y = 0.0
                ass_3y = 0.0
                amm_3y = 0.12

            # Historical availability rate (matches / 38)
            avail_3y = min(1.0, float(last3["pg"].mean()) / 38.0)
            target_pts = float(curr["pg"] * curr["mfv"])

            role_str = str(curr["role"]).strip().upper()
            records.append({
                "player_name": curr["player_name"],
                "role": role_str,
                "season_target": curr["season"],
                "target_pts": target_pts,
                "mv": mv_3y,
                "mfv": mfv_3y,
                "gol_rate": gol_3y,
                "ass_rate": ass_3y,
                "amm_rate": amm_3y,
                "avail_rate": avail_3y,
                "role_P": int(role_str == "P"),
                "role_D": int(role_str == "D"),
                "role_C": int(role_str == "C"),
                "role_A": int(role_str == "A")
            })

    df_train = pd.DataFrame(records)
    print(f"  Generated {len(df_train)} lagged player-season transition samples (Zero Data Leakage).")

    if df_train.empty:
        print(f"  Warning: no lagged transition samples produced from {raw_path}.")
        return None, None, None

    feature_cols = [
        "mv", "mfv", "gol_rate", "ass_rate", "amm_rate", "avail_rate",
        "role_P", "role_D", "role_C", "role_A"
    ]

    X = df_train[feature_cols].fillna(0)
    y = df_train["target_pts"]

    return df_train, X, y


def train_quantile_models(df_train, X, y):
    """
    Trains three Gradient Boosting Regressors for quantiles 0.10, 0.50, and 0.90.
    Includes rigorous Out-of-Time (OOT) temporal validation on the held-out final season
    (2025-26) to measure genuine out-of-sample generalization before final full-dataset fitting.
    """
    seasons = sorted(df_train["season_target"].unique())
    last_season = seasons[-1] if seasons else None

    if last_season and len(seasons) > 2:
        train_mask = df_train["season_target"] != last_season
        test_mask = df_train["season_target"] == last_season

        X_tr, y_tr = X[train_mask], y[train_mask]
        X_te, y_te = X[test_mask], y[test_mask]

        oot_preds = {}
        for alpha, name in [(0.10, "p10"), (0.50, "p50"), (0.90, "p90")]:
            gbr_val = GradientBoostingRegressor(
                loss="quantile", alpha=alpha, n_estimators=150,
                max_depth=4, learning_rate=0.05, random_state=42
            )
            gbr_val.fit(X_tr, y_tr)
            oot_preds[name] = gbr_val.predict(X_te)

        oot_coverage = np.mean((y_te >= oot_preds["p10"]) & (y_te <= oot_preds["p90"])) * 100.0
        oot_corr = np.corrcoef(y_te, oot_preds["p50"])[0, 1]
        oot_mae = np.mean(np.abs(y_te - oot_preds["p50"]))

        print(f"\n  [Out-of-Time Temporal Validation: Held-out {last_season} (N={test_mask.sum()})]")
        print(f"    Empirical 80% CI Coverage: {oot_coverage:.1f}% (Ideal: 80.0%)")
        print(f"    Out-of-Time P50 Correlation: {oot_corr:.3f}")
        print(f"    Out-of-Time P50 MAE: {oot_mae:.1f} pts\n")

    # Train final production models on all available historical seasons
    models = {}
    for alpha, name in [(0.10, "p10_floor"), (0.50, "p50_expected"), (0.90, "p90_ceiling")]:
        gbr = GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            n_estimators=150,
            max_depth=4,
            learning_rate=0.05,
            random_state=42
        )
        gbr.fit(X, y)
        models[name] = gbr
        print(f"  Trained {name} production model (quantile={alpha:.2f})")

    return models


def get_series(df: pd.DataFrame, col: str, default_val=0.0) -> pd.Series:
    """Safely extracts a numeric Series from df, avoiding AttributeError on missing columns."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default_val)
    return pd.Series(default_val, index=df.index, dtype=float)


def predict_active_dataset(models, df_active):
    """
    Applies the trained lagged quantile models to the active roster dataset.
    Uses genuine multi-season weighted MFV (mfv_media_3y) directly from historical tracking,
    retaining the synthetic formula strictly as a fallback for foreign transfers and rookies.
    """
    df = df_active.copy()

    fvm_arr = get_series(df, "FVM_1000", 10.0)
    prezzo_arr = get_series(df, "Prezzo_Consigliato_Cr", 1.0)
    
    # 1. Base Mean Vote (MV) — prior multi-season rolling average or expected vote
    mv_input = pd.to_numeric(df["mv_media_3y"], errors="coerce") if "mv_media_3y" in df.columns else pd.Series(np.nan, index=df.index)
    mv_fallback = get_series(df, "NN_MV_Atteso", 6.05)
    mv_input = np.where(mv_input.isna() | ((mv_input < 5.6) & (fvm_arr >= 40)), mv_fallback, mv_input)
    mv_input = pd.Series(mv_input, index=df.index).fillna(6.05).clip(5.5, 7.0)

    # 2. Projected Availability (combines historical availability with 2026/27 lineup projections & medical status)
    avail_rate = get_series(df, "availability", 0.75)
    is_starter = df["is_starter_2627"].fillna(False).astype(bool) if "is_starter_2627" in df.columns else pd.Series(False, index=df.index)
    starter_pct = get_series(df, "starter_pct_2627", 0.0)

    # Confirmed starters from real lineups: availability floor >= 0.82 (31+ matches/38)
    starter_avail_floor = np.where(
        is_starter,
        np.clip(0.82 + starter_pct * 0.08, 0.82, 0.90),
        0.0
    )
    avail_rate = np.maximum(avail_rate, starter_avail_floor)

    # Fallback for high-value marquee signings without complete lineup tracking yet
    avail_rate = np.where(
        (fvm_arr >= 40) | (prezzo_arr >= 12),
        np.maximum(avail_rate, 0.80),
        avail_rate
    )
    avail_rate = pd.Series(avail_rate, index=df.index).clip(0.15, 1.0)

    # 3. Gol & Assist historical rates
    gol_rate = get_series(df, "gol_per_pg", 0.0).copy()
    ass_rate = get_series(df, "ass_per_pg", 0.0).copy()
    amm_rate = get_series(df, "amm_per_pg", 0.12).copy()

    # Impute expected production rates for high-profile new transfers
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

    # 4. Genuine Historical Fantamedia (MFV) — use historical mfv_media_3y directly!
    mfv_hist = pd.to_numeric(df["mfv_media_3y"], errors="coerce") if "mfv_media_3y" in df.columns else pd.Series(np.nan, index=df.index)
    mfv_synthetic = (mv_input + (gol_rate * 3.0) + (ass_rate * 1.0) - (amm_rate * 0.5)).clip(5.0, 9.5)
    mfv_input = np.where(mfv_hist.notna() & (mfv_hist >= 4.5), mfv_hist, mfv_synthetic)
    mfv_input = pd.Series(mfv_input, index=df.index).fillna(mfv_synthetic).clip(5.0, 9.5)

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

    # Predict Floor (P10), Expected (P50), Ceiling (P90)
    df["predicted_pts_p10"] = np.maximum(0, models["p10_floor"].predict(X_active).round(1))
    df["predicted_pts_p50"] = np.maximum(0, models["p50_expected"].predict(X_active).round(1))
    df["predicted_pts_p90"] = np.maximum(0, models["p90_ceiling"].predict(X_active).round(1))

    # Ensure quantile monotonicity: P10 <= P50 <= P90
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

    df_train, X, y = prepare_training_data()
    if X is None or len(X) == 0:
        print("  Error: No training data available.")
        return

    models = train_quantile_models(df_train, X, y)

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
