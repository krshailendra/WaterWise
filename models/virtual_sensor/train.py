"""Virtual river sensor training (P7): LightGBM quantile models (p10/p50/p90) for
daily NDTI from real features, with honest baselines and uncertainty.

Time split: train <= 2023-12-31, test >= 2024-01-01. Baselines: persistence
(last clear value) and monthly climatology. We report MAE(p50) vs both baselines
and p10-p90 interval coverage. If the model does NOT beat persistence we say so
and keep the better predictor in production (Part C P7 / emergency prompt).

Output: data/gold/virtual_sensor_daily.parquet (provenance=modelled) for every
day 2017->today, with confidence = interval width + days since last clear scene.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from models.virtual_sensor.features import build_features

GOLD = Path("data/gold")
FIGURES = Path("docs/figures")
SPLIT_DATE = pd.Timestamp("2024-01-01")
MODEL_VERSION = "vsensor_lgbm_q@1.0.0"


def _mae(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.mean(np.abs(a[m] - b[m]))) if m.any() else float("nan")


def train_and_predict() -> dict:
    import lightgbm as lgb

    feat = build_features()
    target = feat["ndti_target"]
    X = feat.drop(columns=["ndti_target"])
    feat_cols = list(X.columns)

    labelled = feat[target.notna()]
    train = labelled[labelled.index < SPLIT_DATE]
    test = labelled[labelled.index >= SPLIT_DATE]
    if len(train) < 30 or len(test) < 5:
        return {"error": f"insufficient labelled data (train={len(train)}, test={len(test)})"}

    Xtr, ytr = train[feat_cols], train["ndti_target"]
    Xte, yte = test[feat_cols], test["ndti_target"]

    models = {}
    for alpha in (0.1, 0.5, 0.9):
        m = lgb.LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=300,
                              learning_rate=0.05, num_leaves=31, min_child_samples=10,
                              subsample=0.8, colsample_bytree=0.8, random_state=42,
                              verbose=-1)
        m.fit(Xtr, ytr)
        models[alpha] = m

    # --- test-set predictions ---
    pred = {a: models[a].predict(Xte) for a in models}
    p10, p50, p90 = pred[0.1], pred[0.5], pred[0.9]

    # baselines
    clim = train.copy(); clim["month"] = clim.index.month
    clim_map = clim.groupby("month")["ndti_target"].mean()
    clim_pred = test.index.month.map(clim_map).to_numpy()
    # persistence: last clear NDTI strictly before each test date
    all_series = target.copy()
    persist_pred = []
    for d in test.index:
        prior = all_series[(all_series.index < d) & all_series.notna()]
        persist_pred.append(prior.iloc[-1] if len(prior) else np.nan)
    persist_pred = np.array(persist_pred, float)

    mae_model = _mae(p50, yte)
    mae_persist = _mae(persist_pred, yte)
    mae_clim = _mae(clim_pred, yte)
    coverage = float(np.mean((yte.to_numpy() >= p10) & (yte.to_numpy() <= p90)))

    # per-season MAE
    season_mae = {}
    for name, months in {"monsoon(JJAS)": [6, 7, 8, 9], "winter(DJF)": [12, 1, 2],
                         "pre_monsoon(MAM)": [3, 4, 5], "post(ON)": [10, 11]}.items():
        mask = test.index.month.isin(months)
        if mask.any():
            season_mae[name] = round(_mae(p50[mask], yte[mask.to_numpy() if hasattr(mask, 'to_numpy') else mask]), 4)

    beats_persistence = mae_model < mae_persist
    production = "lgbm_p50" if beats_persistence else "persistence"

    # --- predict for ALL days (fill cloudy gaps) ---
    fullX = X[feat_cols]
    full = pd.DataFrame(index=feat.index)
    full["ndti_p10"] = models[0.1].predict(fullX)
    full["ndti_p50"] = models[0.5].predict(fullX)
    full["ndti_p90"] = models[0.9].predict(fullX)
    # enforce monotone quantiles
    full["ndti_p10"] = np.minimum(full["ndti_p10"], full["ndti_p50"])
    full["ndti_p90"] = np.maximum(full["ndti_p90"], full["ndti_p50"])
    full["interval_width"] = full["ndti_p90"] - full["ndti_p10"]
    # persistence (production predictor when it beats the model): last clear value
    full["ndti_persistence"] = target.reindex(full.index).ffill()
    # days since last clear satellite obs
    clear = target.reindex(full.index).notna()
    last_clear = pd.Series(pd.NaT, index=full.index, dtype="datetime64[ns]")
    last_clear[clear.to_numpy()] = full.index[clear.to_numpy()]
    last_clear = last_clear.ffill()
    full["days_since_last_clear"] = (full.index.to_series() - last_clear).dt.days
    full["ndti_observed"] = target
    full = full.reset_index().rename(columns={"index": "date"})
    full["provenance"] = "modelled"
    full["source_id"] = "virtual_sensor"
    full["source_ref"] = (f"{MODEL_VERSION} | LightGBM quantile on real rain/discharge/"
                          f"temp features | production={production}")
    GOLD.mkdir(parents=True, exist_ok=True)
    full.to_parquet(GOLD / "virtual_sensor_daily.parquet", index=False)

    # --- plot ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        FIGURES.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(11, 4.5))
        f2 = full.set_index("date")
        ax.fill_between(f2.index, f2["ndti_p10"], f2["ndti_p90"], alpha=0.2,
                        label="p10-p90 band")
        ax.plot(f2.index, f2["ndti_p50"], lw=0.8, label="virtual sensor p50")
        obs = f2[f2["ndti_observed"].notna()]
        ax.scatter(obs.index, obs["ndti_observed"], s=8, c="k", label="S2 observed", zorder=3)
        ax.axvline(SPLIT_DATE, color="r", ls="--", lw=0.8, label="train/test split")
        ax.set_title(f"Virtual river sensor — daily NDTI (MAE p50={mae_model:.4f} vs "
                     f"persistence {mae_persist:.4f})")
        ax.set_ylabel("NDTI"); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(FIGURES / "virtual_sensor.png", dpi=120)
        plt.close(fig)
    except Exception as e:  # noqa: BLE001
        print("[vsensor] plot skipped:", e)

    return {"train_n": len(train), "test_n": len(test),
            "mae_p50_model": round(mae_model, 4),
            "mae_persistence": round(mae_persist, 4),
            "mae_climatology": round(mae_clim, 4),
            "beats_persistence": beats_persistence,
            "beats_climatology": mae_model < mae_clim,
            "p10_p90_coverage": round(coverage, 3),
            "season_mae": season_mae,
            "production_predictor": production,
            "predictions_written": len(full)}


if __name__ == "__main__":
    import json
    r = train_and_predict()
    print(json.dumps(r, indent=2, default=str))
