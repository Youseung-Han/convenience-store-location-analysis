"""Construct a calendar-lagged panel and evaluate a fixed set of regressors."""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import KEY, STORE_FIELDS, require_unique


STORE_INPUTS = [f"lag_{name}" for name in STORE_FIELDS.values()]
INPUTS = ["lag_sales", "lag_sales_per_store", *STORE_INPUTS]
VALIDATION = ("2022Q1", "2022Q2")
TEST = "2022Q4"


def convenience(frame):
    return frame.loc[frame["industry"].eq("CS300002")].copy()


def make_panel(sales, stores):
    sales_c = convenience(sales)
    stores_c = convenience(stores)
    require_unique(sales_c, KEY)
    require_unique(stores_c, KEY)
    identity = ["type", "name"]
    all_keys = pd.concat([sales[KEY + identity], stores[KEY + identity]])
    all_keys = all_keys.drop_duplicates()
    require_unique(all_keys, KEY)
    panel = all_keys.merge(sales_c[KEY + ["sales"]], on=KEY, how="left", validate="one_to_one")
    panel = panel.merge(stores_c[KEY + list(STORE_FIELDS.values())],
                        on=KEY, how="left", validate="one_to_one")
    panel["target"] = panel["sales"].div(panel["stores"].where(panel["stores"] > 0))
    matches = sales_c[KEY].merge(stores_c[KEY], on=KEY, how="outer",
                                 validate="one_to_one", indicator=True)
    qa = {}
    for quarter, frame in panel.groupby("quarter"):
        counts = matches.loc[matches["quarter"].eq(quarter), "_merge"].value_counts()
        matched = int(counts.get("both", 0))
        n_sales = matched + int(counts.get("left_only", 0))
        n_stores = matched + int(counts.get("right_only", 0))
        qa[str(quarter)] = {
            "all_area_rows": len(frame), "convenience_sales_rows": n_sales,
            "convenience_store_rows": n_stores, "matched": matched,
            "sales_join_rate": matched / n_sales if n_sales else None,
            "stores_join_rate": matched / n_stores if n_stores else None,
            "zero_store": int(frame["stores"].eq(0).sum()),
            "missing_store": int(frame["stores"].isna().sum()),
            "missing_sales": int(frame["sales"].isna().sum()),
            "observed_zero_sales": int(frame["sales"].eq(0).sum()),
            "excluded_target": int(frame["target"].isna().sum()),
            "usable_target": int(frame["target"].notna().sum()),
        }
    membership = []
    for quarter, frame in panel.groupby("quarter"):
        now = set(frame["area"])
        before = set(panel.loc[panel["quarter"].eq(quarter - 1), "area"])
        if before:
            membership.append({"quarter": str(quarter), "new_codes": len(now - before),
                               "absent_codes": len(before - now)})
    qa["code_audit"] = {
        "membership_changes": membership,
        "codes_with_multiple_names": int(panel.groupby("area")["name"].nunique().gt(1).sum()),
        "codes_with_multiple_types": int(panel.groupby("area")["type"].nunique().gt(1).sum()),
        "names_with_multiple_codes": int(panel.groupby(["type", "name"])["area"].nunique().gt(1).sum()),
        "remap": "none",
    }
    return panel.sort_values(KEY), qa


def lag_panel(panel, lag):
    if lag < 2:
        raise ValueError("lag must be at least two calendar quarters")
    require_unique(panel, KEY)
    fields = {"sales": "lag_sales", "target": "lag_sales_per_store"}
    fields.update({name: f"lag_{name}" for name in STORE_FIELDS.values()})
    previous = panel[KEY + ["name", "type", *fields]].rename(columns=fields)
    previous["feature_quarter"] = previous["quarter"]
    previous["quarter"] += lag
    # The scoring roster comes entirely from past records, including areas without target rows.
    previous = previous.loc[previous["lag_sales_per_store"].notna()]
    targets = panel[KEY + ["target"]]
    result = previous.merge(targets, on=KEY, how="left", validate="one_to_one")
    if not result["quarter"].eq(result["feature_quarter"] + lag).all():
        raise ValueError("feature quarter is inconsistent")
    return result.sort_values(KEY)


def split(lagged, quarter, lag):
    observed = lagged["target"].notna()
    train = lagged.loc[observed & lagged["quarter"].le(quarter - lag)]
    score = lagged.loc[lagged["quarter"].eq(quarter)]
    return train, score


def model_factories():
    return {
        "ridge": lambda: make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(), Ridge(alpha=10.0),
        ),
        "random_forest": lambda: make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            RandomForestRegressor(n_estimators=200, min_samples_leaf=10,
                                  max_features=1.0, random_state=42, n_jobs=1),
        ),
    }


def score_fold(lagged, quarter, lag):
    train, score = split(lagged, pd.Period(quarter, freq="Q"), lag)
    observed = score["target"].notna()
    if train.empty or not observed.any():
        raise ValueError(f"{quarter}: train or common evaluation sample is empty")
    fitted = score.copy()
    fitted["baseline"] = score["lag_sales_per_store"]
    for name, factory in model_factories().items():
        for suffix, columns in [("", INPUTS), ("_no_sales", STORE_INPUTS)]:
            model = factory().fit(train[columns], train["target"])
            fitted[name + suffix] = np.maximum(0, model.predict(score[columns]))
    actual = fitted.loc[observed, "target"]
    rows = []
    for name in ("baseline", "ridge", "random_forest", "ridge_no_sales", "random_forest_no_sales"):
        predicted = fitted.loc[observed, name]
        errors = (predicted - actual).abs()
        rows.append({
            "quarter": quarter, "model": name, "n_train": len(train),
            "training_latest_quarter": str(train["quarter"].max()),
            "n_scored": len(fitted), "n_evaluated": len(actual),
            "n_scored_missing_target": len(fitted) - len(actual),
            "mae_krw_per_store": errors.mean(),
            "wape_pct": errors.sum() / actual.abs().sum() * 100 if actual.abs().sum() else np.nan,
            "spearman": (spearmanr(actual, predicted).statistic
                         if actual.nunique() > 1 and predicted.nunique() > 1 else np.nan),
        })
    return rows, fitted


def evaluate(panel, lag):
    lagged = lag_panel(panel, lag)
    rows = []
    for quarter in VALIDATION:
        validation, _ = score_fold(lagged, quarter, lag)
        rows.extend(validation)
    metrics = pd.DataFrame(rows)
    contenders = metrics.loc[metrics["model"].isin(["baseline", *model_factories()])]
    # Equal weight to each validation quarter. Name order breaks exact ties.
    selected = contenders.groupby("model")["mae_krw_per_store"].mean().idxmin()
    test, scored = score_fold(lagged, TEST, lag)
    return pd.DataFrame(rows + test), selected, scored


def transaction_weight(sales, quarter):
    prior = sales.loc[sales["quarter"].eq(quarter) & sales["industry"].ne("CS300002")]
    counts = prior.groupby("area")["transactions"]
    weights = counts.sum(min_count=1).where(counts.count().eq(counts.size()))
    return weights.rename("weight").reset_index()
