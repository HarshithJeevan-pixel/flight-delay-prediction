"""
AeroDelay Ops - Train Arrival Delay Model on 2023 + Jan-Apr 2024
Evaluated on Held-Out Test Set: June - July 2024 (Validation: May 2024)
"""

import json
import time
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    average_precision_score, confusion_matrix, precision_recall_curve, roc_curve
)
import joblib

warnings.filterwarnings("ignore")

BASE_DIR = Path("D:/Downloads/2ndyear/ML-2026/SHANMUKHA")
WEBSITE_DIR = BASE_DIR / "flight-delay-website"
DATA_DIR = WEBSITE_DIR / "data"
MODEL_DIR = WEBSITE_DIR / "model"
RAW_DIR = BASE_DIR / "raw_data"

RANDOM_STATE = 42
WARMUP_DAYS = 30
HIST_WINDOW = 30
LR_C_GRID = [0.01, 0.1, 1, 10]
HGB_CONFIGS = [
    dict(learning_rate=0.1, max_leaf_nodes=31, min_samples_leaf=100),
    dict(learning_rate=0.05, max_leaf_nodes=63, min_samples_leaf=200),
    dict(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=50)
]
HGB_MAX_ITER = 200
N_BOOT = 200

print("[1/6] Loading source datasets...")
t0 = time.time()
df_2023 = pd.read_parquet(DATA_DIR / "bts_2023_arrival_clean.parquet")
print(f"Loaded 2023 dataset: {len(df_2023):,} rows")

df_w24 = pd.read_parquet(DATA_DIR / "flights_weather_2024_10airports.parquet")
df_bts24 = pd.read_parquet(RAW_DIR / "bts_2024_jan_jul.parquet")
print(f"Loaded 2024 weather parquet: {len(df_w24):,} rows, 2024 BTS parquet: {len(df_bts24):,} rows")

print("\n[2/6] Building aircraft rotation features from 2024 BTS data...")
tail = df_bts24.copy()
tail['FL_DATE'] = pd.to_datetime(tail['FL_DATE']).dt.normalize()
for c in ["OP_CARRIER_FL_NUM", "CRS_DEP_TIME", "CRS_ARR_TIME", "DEP_DELAY", "ARR_DELAY"]:
    tail[c] = pd.to_numeric(tail[c], errors="coerce")
for c in ["ORIGIN", "DEST", "TAIL_NUM"]:
    tail[c] = tail[c].astype("string").str.strip().str.upper()

tail = tail.dropna(subset=["FL_DATE", "OP_CARRIER_FL_NUM", "CRS_DEP_TIME", "ORIGIN", "DEST"])
tail = tail.drop_duplicates()
tail["OP_CARRIER_FL_NUM"] = tail["OP_CARRIER_FL_NUM"].astype("int64")
tail["CRS_DEP_TIME"] = tail["CRS_DEP_TIME"].astype("int64")

airports = pd.Index(sorted(set(tail["ORIGIN"].dropna()) | set(tail["DEST"].dropna())))
tail["_o"] = airports.get_indexer(tail["ORIGIN"]).astype("int16")
tail["_d"] = airports.get_indexer(tail["DEST"]).astype("int16")
tail["_dep_min"] = (tail["CRS_DEP_TIME"] // 100) * 60 + tail["CRS_DEP_TIME"] % 100
tail["_arr_min"] = (tail["CRS_ARR_TIME"] // 100) * 60 + tail["CRS_ARR_TIME"] % 100
tail["TAIL_NUM"] = tail["TAIL_NUM"].astype("category")

t = tail[tail["TAIL_NUM"].notna()].sort_values(["TAIL_NUM", "FL_DATE", "_dep_min", "OP_CARRIER_FL_NUM"], kind="mergesort")
g = t.groupby(["TAIL_NUM", "FL_DATE"], sort=False, observed=True)

t["tail_leg_of_day"] = g.cumcount() + 1
prev = g[["_d", "ARR_DELAY", "DEP_DELAY", "_arr_min"]].shift(1)
chain_ok = prev["_d"].eq(t["_o"])
t["prev_arr_delay"] = prev["ARR_DELAY"].where(chain_ok)
t["prev_dep_delay"] = prev["DEP_DELAY"].where(chain_ok)
turn = (t["_dep_min"] - prev["_arr_min"]).where(chain_ok)
t["sched_turn_min"] = turn.where(turn >= 0)

arr0 = t["ARR_DELAY"].fillna(0)
valid = t["ARR_DELAY"].notna().astype(float)
t["_arr0"], t["_valid"] = arr0, valid
cum_sum = g["_arr0"].cumsum() - arr0
cum_n = g["_valid"].cumsum() - valid
t["prev_legs_mean_arr_delay"] = (cum_sum / cum_n.where(cum_n > 0))

TAIL_FEATS = ["tail_leg_of_day", "prev_arr_delay", "prev_dep_delay", "sched_turn_min", "prev_legs_mean_arr_delay"]
KEYS_TAIL = ["FL_DATE", "OP_CARRIER_FL_NUM", "ORIGIN", "DEST", "CRS_DEP_TIME"]
slim = tail[KEYS_TAIL + ["ARR_DELAY"]].join(t[TAIL_FEATS])
slim = slim.drop_duplicates(KEYS_TAIL, keep="first")
slim["ORIGIN"] = slim["ORIGIN"].astype(str)
slim["DEST"] = slim["DEST"].astype(str)
del t, g, prev, tail

print("\n[3/6] Merging with 2024 weather and preparing features...")
df_2024 = df_w24[df_w24['month'].isin([1, 2, 3, 4, 5, 6, 7])].copy()
df_2024 = df_2024.drop(columns=["arr_delay_min", "arr_del15"], errors="ignore")
df_2024['flight_date'] = pd.to_datetime(df_2024['flight_date']).dt.normalize()
for c in ["airline", "origin", "dest"]:
    df_2024[c] = df_2024[c].astype(str)
df_2024["flight_number"] = df_2024["flight_number"].astype("int64")
df_2024["crs_dep_time"] = df_2024["crs_dep_time"].astype("int64")

left_keys = ["flight_date", "flight_number", "origin", "dest", "crs_dep_time"]
df_2024 = df_2024.merge(slim, left_on=left_keys, right_on=KEYS_TAIL, how="left")
df_2024 = df_2024.drop(columns=KEYS_TAIL)

# Filter matched
df_2024 = df_2024[df_2024["ARR_DELAY"].notna()].copy()
df_2024 = df_2024.rename(columns={"ARR_DELAY": "arr_delay_min"})
df_2024["arr_del15"] = (df_2024["arr_delay_min"] >= 15).astype("int8")

# Step features
df_2024["dep_delay_clip"] = df_2024["dep_delay_min"].clip(-30, 300)
df_2024["dep_late_15"] = (df_2024["dep_delay_min"] >= 15).astype(int)
df_2024["dep_late_30"] = (df_2024["dep_delay_min"] >= 30).astype(int)
df_2024["dep_late_60"] = (df_2024["dep_delay_min"] >= 60).astype(int)

# Scheduled elapsed flight duration in minutes
route_med = df_2023.groupby(['origin', 'dest'])['crs_elapsed_min'].median().to_dict()
df_2024['route_med_elapsed'] = df_2024.set_index(['origin', 'dest']).index.map(route_med).fillna(150.0)
dep_m = (df_2024['crs_dep_time'] // 100) * 60 + (df_2024['crs_dep_time'] % 100)
arr_m = (df_2024['crs_arr_time'] // 100) * 60 + (df_2024['crs_arr_time'] % 100)
raw_d = (arr_m - dep_m) % 1440
tz_off = ((raw_d - df_2024['route_med_elapsed'] + 30) // 60) * 60
df_2024['crs_elapsed_min'] = ((raw_d - tz_off) % 1440).clip(30, 600).astype(int)
df_2024 = df_2024.drop(columns=['route_med_elapsed'])

# Holiday window
cal = USFederalHolidayCalendar()
holidays = cal.holidays(start="2022-12-01", end="2024-08-31")
days = pd.date_range("2022-12-01", "2024-08-31")
near = pd.Series(0, index=days)
for h in holidays:
    near.loc[h - pd.Timedelta(days=3): h + pd.Timedelta(days=3)] = 1
df_2024["is_holiday_window"] = df_2024["flight_date"].map(near).fillna(0).astype(int)

# Bad wind readings
bad_wind = ((df_2024["wx_gust_kt"] < df_2024["wx_wind_kt"]) & (df_2024["wx_has_gust"] == 1)) | \
           ((df_2024["wx_wind_kt"] >= 35) & (df_2024["wx_has_gust"] == 0))
df_2024.loc[bad_wind, "wx_wind_kt"] = np.nan

# Split assignment for 2024
conditions_2024 = [
    df_2024['month'].isin([1, 2, 3, 4]),
    df_2024['month'] == 5,
    df_2024['month'].isin([6, 7])
]
choices_2024 = ['train', 'validation', 'test']
df_2024['split'] = np.select(conditions_2024, choices_2024, default='unseen')

# Set all 2023 data to 'train'
df_2023['split'] = 'train'

# Combine 2023 and 2024
common_cols = [c for c in df_2023.columns if c in df_2024.columns and c not in [
    'hist_route_arr_rate', 'hist_airline_arr_rate', 'hist_origin_arr_rate'
]]
combined = pd.concat([df_2023[common_cols], df_2024[common_cols]], ignore_index=True)
combined = combined.sort_values(["flight_date", "crs_dep_time"]).reset_index(drop=True)

# Recompute trailing 30-day rates across continuous 2023-2024 timeline
def add_trailing_rate(data, keys, name, target="arr_del15", window_days=HIST_WINDOW, min_n=20):
    daily = (data.groupby(keys + ["flight_date"])[target].agg(n="size", k="sum")
                 .reset_index().sort_values("flight_date").set_index("flight_date"))
    roll = daily.groupby(keys)[["n", "k"]].rolling(f"{window_days}D", closed="left").sum().reset_index()
    roll[name] = np.where(roll["n"] >= min_n, roll["k"] / roll["n"], np.nan)
    return data.merge(roll[keys + ["flight_date", name]], on=keys + ["flight_date"], how="left")

combined = add_trailing_rate(combined, ["route"], "hist_route_arr_rate", min_n=20)
combined = add_trailing_rate(combined, ["airline"], "hist_airline_arr_rate", min_n=50)
combined = add_trailing_rate(combined, ["origin"], "hist_origin_arr_rate", min_n=50)

for c in ["sched_dep_hour", "day_of_week"]:
    combined[c] = combined[c].astype(str)
combined["wx_sky_cover"] = combined["wx_sky_cover"].fillna("UNK").astype(str)

CAT = ["airline", "origin", "dest", "sched_dep_hour", "day_of_week", "wx_sky_cover"]
WX_FLAGS = ["wx_has_gust", "wx_rain", "wx_snow", "wx_thunder", "wx_fog", "wx_mist", "wx_drizzle",
            "wx_haze", "wx_freezing", "wx_ice_hail", "wx_heavy"]
NUM = (["distance_mi", "crs_elapsed_min", "is_holiday_window", "wx_temp_f", "wx_wind_kt", "wx_gust_kt", "wx_vis_mi",
        "wx_precip_1h_in", "wx_ceiling_ft"] + WX_FLAGS +
       ["hist_route_arr_rate", "hist_airline_arr_rate", "hist_origin_arr_rate"] +
       ["dep_delay_clip", "dep_late_15", "dep_late_30", "dep_late_60"] +
       [c for c in TAIL_FEATS if combined[c].notna().any()])
FEATURES = CAT + NUM

print(f"Total features: {len(FEATURES)}")

# Splits:
train = combined[combined["split"] == "train"].reset_index(drop=True)
val   = combined[combined["split"] == "validation"].reset_index(drop=True)
test  = combined[combined["split"] == "test"].reset_index(drop=True)

print("\nDataset split summary:")
print(f"  Train (2023-01 to 2024-04):      {len(train):,} flights (late rate: {train['arr_del15'].mean():.1%})")
print(f"  Validation (May 2024):            {len(val):,} flights (late rate: {val['arr_del15'].mean():.1%})")
print(f"  Held-Out Test (Jun - Jul 2024):   {len(test):,} flights (late rate: {test['arr_del15'].mean():.1%})")

X_train, y_train = train[FEATURES], train["arr_del15"].values
X_val,   y_val   = val[FEATURES],   val["arr_del15"].values
X_test,  y_test  = test[FEATURES],  test["arr_del15"].values

print("\n[4/6] Training machine learning models...")

def make_preprocessor(for_linear):
    num = [("imp", SimpleImputer(strategy="median"))]
    if for_linear:
        num.append(("scale", StandardScaler()))
    ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=for_linear, dtype=np.float32)
    return ColumnTransformer([("num", Pipeline(num), NUM), ("cat", ohe, CAT)],
                             sparse_threshold=0.3 if for_linear else 0.0)

def best_f1_threshold(y, s):
    p, r, t = precision_recall_curve(y, s)
    f1 = 2 * p * r / np.clip(p + r, 1e-12, None)
    return float(t[np.argmax(f1[:-1])])

def metrics_at(y, s, thr):
    pred = (s >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "threshold": round(float(thr), 4),
        "accuracy": accuracy_score(y, pred),
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "roc_auc": roc_auc_score(y, s),
        "pr_auc": average_precision_score(y, s),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)
    }

scores_val, scores_test = {}, {}

# 1. Baselines
scores_val["Departure-delay rule"]  = val["dep_delay_min"].clip(-60, 600).values.astype(float)
scores_test["Departure-delay rule"] = test["dep_delay_min"].clip(-60, 600).values.astype(float)
scores_val["Majority-class baseline"]  = np.zeros(len(val))
scores_test["Majority-class baseline"] = np.zeros(len(test))

# 2. Logistic Regression
print("  Fitting Logistic Regression...")
prep_lr = make_preprocessor(True).fit(X_train)
Xtr, Xva = prep_lr.transform(X_train), prep_lr.transform(X_val)

best_lr = None
for C in LR_C_GRID:
    clf = LogisticRegression(C=C, class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE).fit(Xtr, y_train)
    ap = average_precision_score(y_val, clf.predict_proba(Xva)[:, 1])
    print(f"    C={C} -> Val PR-AUC = {ap:.4f}")
    if best_lr is None or ap > best_lr[0]:
        best_lr = (ap, C, clf)

lr_pipe = Pipeline([("prep", prep_lr), ("clf", best_lr[2])])
scores_val["Logistic regression"]  = lr_pipe.predict_proba(X_val)[:, 1]
scores_test["Logistic regression"] = lr_pipe.predict_proba(X_test)[:, 1]

# 3. HistGradientBoostingClassifier
print("  Fitting Gradient Boosting (HistGradientBoosting)...")
prep_rf = make_preprocessor(False).fit(X_train)
Xtr_rf, Xva_rf = prep_rf.transform(X_train), prep_rf.transform(X_val)

best_hgb = None
for cfg in HGB_CONFIGS:
    h = HistGradientBoostingClassifier(max_iter=HGB_MAX_ITER, class_weight="balanced", random_state=RANDOM_STATE, **cfg)
    h.fit(Xtr_rf, y_train)
    ap = average_precision_score(y_val, h.predict_proba(Xva_rf)[:, 1])
    print(f"    {cfg} -> Val PR-AUC = {ap:.4f}")
    if best_hgb is None or ap > best_hgb[0]:
        best_hgb = (ap, cfg, h)

hgb_pipe = Pipeline([("prep", prep_rf), ("clf", best_hgb[2])])
scores_val["Gradient boosting"]  = hgb_pipe.predict_proba(X_val)[:, 1]
scores_test["Gradient boosting"] = hgb_pipe.predict_proba(X_test)[:, 1]

# 4. Random Forest (on sample for feature importance and benchmark)
print("  Fitting Random Forest benchmark...")
rng = np.random.RandomState(RANDOM_STATE)
idx = rng.choice(len(Xtr_rf), size=min(150_000, len(Xtr_rf)), replace=False)
rf = RandomForestClassifier(n_estimators=100, max_depth=16, min_samples_leaf=50, max_features="sqrt",
                            class_weight="balanced_subsample", n_jobs=-1, random_state=RANDOM_STATE).fit(Xtr_rf[idx], y_train[idx])
rf_pipe = Pipeline([("prep", prep_rf), ("clf", rf)])
scores_val["Random forest"]  = rf_pipe.predict_proba(X_val)[:, 1]
scores_test["Random forest"] = rf_pipe.predict_proba(X_test)[:, 1]

print("\n[5/6] Evaluating on Held-Out Test Set (Jun - Jul 2024)...")
MODELS = ["Majority-class baseline", "Departure-delay rule", "Logistic regression", "Random forest", "Gradient boosting"]
FITTED = MODELS[2:]

thresholds = {"Majority-class baseline": 1.0}
for m in MODELS[1:]:
    thresholds[m] = best_f1_threshold(y_val, scores_val[m])

val_table  = pd.DataFrame({m: metrics_at(y_val,  scores_val[m],  thresholds[m]) for m in MODELS}).T
test_table = pd.DataFrame({m: metrics_at(y_test, scores_test[m], thresholds[m]) for m in MODELS}).T

show = ["threshold", "pr_auc", "roc_auc", "accuracy", "precision", "recall", "f1"]
final = test_table[show + ["tn", "fp", "fn", "tp"]].copy()
final[show] = final[show].astype(float).round(3)
final[["tn", "fp", "fn", "tp"]] = final[["tn", "fp", "fn", "tp"]].astype(int)

print("=" * 86)
print("SCORECARD - ARRIVAL DELAY AFTER DEPARTURE - TEST SET (Jun-Jul 2024)")
print("=" * 86)
print(final.to_string())

# Bootstrap test
print("\nRunning 200-sample bootstrap significance test...")
rng = np.random.RandomState(RANDOM_STATE)
nt = len(y_test)
boot = {m: [] for m in MODELS[1:]}
for _ in range(N_BOOT):
    i = rng.randint(0, nt, nt)
    for m in MODELS[1:]:
        boot[m].append(average_precision_score(y_test[i], scores_test[m][i]))
boot = {m: np.array(v) for m, v in boot.items()}

boot_rows = []
for m in FITTED:
    gain = boot[m] - boot["Departure-delay rule"]
    lo, hi = np.percentile(gain, [2.5, 97.5])
    boot_rows.append({
        "model": m,
        "PR-AUC gain vs departure-delay rule": round(float(gain.mean()), 4),
        "95% interval": f"[{lo:.4f}, {hi:.4f}]",
        "gain larger than noise?": "yes" if lo > 0 else "no"
    })
boot_table = pd.DataFrame(boot_rows)
print(boot_table.to_string(index=False))

# Permutation feature importance
print("\nComputing permutation feature importance...")
smp = val.sample(min(10000, len(val)), random_state=RANDOM_STATE)
pi = permutation_importance(hgb_pipe, smp[FEATURES], smp["arr_del15"], scoring="average_precision",
                            n_repeats=3, random_state=RANDOM_STATE, n_jobs=1)
perm = pd.Series(pi.importances_mean, index=FEATURES).sort_values(ascending=False).head(15)
names = prep_rf.get_feature_names_out()
rf_imp = pd.Series(rf.feature_importances_, index=names).sort_values(ascending=False).head(15)

print("\n[6/6] Exporting artifacts and updating website database...")
grid_t = np.round(np.arange(0, 1.0001, 0.01), 2)
web = {
    "task": "arrival delay (15+ min) after departure",
    "test_period": "2024-06 to 2024-07",
    "n_test": int(len(y_test)),
    "late_rate_test": float(y_test.mean()),
    "models": {}
}

for m in FITTED:
    s = scores_test[m]
    rows = []
    for th in grid_t:
        pred = s >= th
        tp = int((pred & (y_test == 1)).sum())
        fp = int((pred & (y_test == 0)).sum())
        fn = int((~pred & (y_test == 1)).sum())
        tn = int((~pred & (y_test == 0)).sum())
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1_val = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        rows.append({
            "threshold": float(th), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": pr, "recall": rc, "f1": f1_val
        })
    p, r, _ = precision_recall_curve(y_test, s)
    keep = np.linspace(0, len(p) - 1, min(200, len(p))).astype(int)
    web["models"][m] = {
        "chosen_threshold": float(thresholds[m]),
        "pr_auc": float(average_precision_score(y_test, s)),
        "roc_auc": float(roc_auc_score(y_test, s)),
        "by_threshold": rows,
        "pr_curve": {"precision": p[keep].round(4).tolist(), "recall": r[keep].round(4).tolist()}
    }

web["feature_importance"] = {
    "random_forest_builtin": rf_imp.round(5).to_dict(),
    "permutation_best_model": perm.round(5).to_dict(),
    "best_model": "Gradient boosting"
}
web["bootstrap_pr_auc_gain"] = boot_table.to_dict(orient="records")

# Save results JSON
with open(MODEL_DIR / "arrival_results_for_website.json", "w") as f:
    json.dump(web, f, indent=2)
print("Saved model/arrival_results_for_website.json")

# Save trained models
joblib.dump({
    'Logistic regression': lr_pipe,
    'Gradient boosting': hgb_pipe,
    'thresholds': thresholds,
    'features': FEATURES
}, MODEL_DIR / 'arrival_models.joblib', compress=3)
print("Saved model/arrival_models.joblib")

# Update 2024 parquet with clean ground truth
print("Enriching flights_weather_2024_10airports.parquet with arrival ground truth...")
df_w24_enriched = df_w24.copy()
left_k = ["flight_date", "flight_number", "origin", "dest", "crs_dep_time"]
gt_map = df_2024[left_k + ["arr_delay_min", "arr_del15", "crs_elapsed_min", "tail_leg_of_day", "prev_arr_delay", "prev_dep_delay", "sched_turn_min"]].drop_duplicates(left_k)
gt_map["_match_date"] = gt_map["flight_date"].dt.strftime('%Y-%m-%d')
gt_map = gt_map.drop(columns=["flight_date"])

df_w24_enriched["_match_date"] = pd.to_datetime(df_w24_enriched["flight_date"]).dt.strftime('%Y-%m-%d')
df_w24_enriched = df_w24_enriched.drop(columns=["arr_delay_min", "arr_del15", "crs_elapsed_min"], errors="ignore")
merge_k = ["_match_date", "flight_number", "origin", "dest", "crs_dep_time"]
df_w24_enriched = df_w24_enriched.merge(gt_map, on=merge_k, how="left")
df_w24_enriched = df_w24_enriched.drop(columns=["_match_date"], errors="ignore")
df_w24_enriched.to_parquet(DATA_DIR / "flights_weather_2024_10airports.parquet", index=False)
print("Updated data/flights_weather_2024_10airports.parquet with actual arrival outcomes!")

elapsed = time.time() - t0
print(f"\nAll operations finished successfully in {elapsed:.1f}s ({elapsed/60:.1f}m)!")
