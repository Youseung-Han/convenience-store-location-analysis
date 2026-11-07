"""Run eligible analysis stages and report missing evidence explicitly."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .data import CUTOFF, audit_source, download, read_quarters
from .model import TEST, evaluate, make_panel, transaction_weight
from .spatial import (compare, coverage_matrix, covered_weight, draw_map, read_areas,
                      solve, spatial_inputs)


TABULAR = ("sales-2021", "sales-2022", "stores-2021", "stores-2022")


def write_json(out, name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_table(out, name, frame):
    frame.to_csv(out / name, index=False, encoding="utf-8-sig", float_format="%.8f")


def area_check(out, areas, boundaries):
    district_sizes = areas.groupby(["district_code", "district"], as_index=False).size()
    district_sizes = district_sizes.sort_values(["size", "district_code"], ascending=[False, True])
    sample = areas.loc[areas["district_code"].eq(district_sizes.iloc[0]["district_code"])]
    weights = np.ones(len(sample))
    matrix = coverage_matrix(sample, sample, 500)
    selected = solve(matrix, weights, np.zeros(len(sample)), 5)
    covered = matrix[:, selected].any(axis=1)
    if not np.array_equal(matrix, matrix.T) or not np.diag(matrix).all():
        raise RuntimeError("coverage distance matrix failed symmetry or self-coverage check")
    draw_map(out / "area_validation.png", sample, sample, boundaries,
             {f"{int(covered.sum())} / {len(sample)} area points covered": (sample.iloc[selected], covered)},
             "Geometry validation | 2023 area snapshot")
    return {
        "area_codes": len(areas), "districts": len(district_sizes), "crs": "EPSG:5181",
        "unique_area_key": True, "representative_points_in_seoul_bbox": True,
        "points_outside_own_shape_bbox": int((~areas["point_inside_shape_bbox"]).sum()),
        "duplicate_representative_coordinate_rows": int(areas.duplicated(["x", "y"], keep=False).sum()),
        "geometry_demo_district": sample.iloc[0]["district"],
        "geometry_demo_selection_rule": "largest district by area count, then district code",
        "geometry_demo_sites": sample.iloc[selected]["area"].tolist(),
        "geometry_demo_demand_points": len(sample),
        "geometry_demo_covered_points": int(covered_weight(matrix, weights, selected)),
        "geometry_demo_radius_m": 500, "geometry_demo_selected_count": len(selected),
        "geometry_demo_source": "OA-15560; uniform weight per representative point",
    }


def run(raw, out, manifest, lag):
    out.mkdir(parents=True, exist_ok=True)
    provenance = {key: audit_source(raw, entry) for key, entry in manifest.items()}
    model_ready = all(provenance.get(key, {}).get("eligible") for key in TABULAR)
    area_ready = provenance.get("areas", {}).get("eligible", False)
    if ((not model_ready and (out / "model_comparison.csv").exists())
            or (not (model_ready and area_ready) and (out / "strategy_summary.csv").exists())):
        raise ValueError("use a separate output directory to preserve the earlier run")
    quality = {"cutoff_kst": CUTOFF.isoformat(), "sources": provenance}
    status = {
        "seoul_model": "미실행", "strategy_comparison": "미실행",
        "area_geometry": "미실행", "population_weight": "미실행", "2023_extension": "미실행",
    }
    areas, boundaries = None, None
    if area_ready:
        areas, boundaries = read_areas(raw / manifest["areas"]["path"])
        quality["area"] = area_check(out, areas, boundaries)
        status["area_geometry"] = "검증 완료"
    if not model_ready:
        status["model_reason"] = "2021–2022 매출·점포 원본의 기준일 적격성 미확인"
        status["strategy_reason"] = "적격한 서울 전체 예측값 부재"
        write_json(out, "data_quality.json", quality)
        write_json(out, "run_status.json", status)
        return status

    units = {manifest[f"sales-{year}"]["sales_unit"] for year in (2021, 2022)}
    if len(units) != 1:
        raise ValueError("sales aggregation units differ across years")
    sales_unit = units.pop()
    sales = pd.concat([
        read_quarters(raw / manifest[f"sales-{year}"]["path"], "sales", year, sales_unit)
        for year in (2021, 2022)
    ], ignore_index=True)
    stores = pd.concat([
        read_quarters(raw / manifest[f"stores-{year}"]["path"], "stores", year)
        for year in (2021, 2022)
    ], ignore_index=True)
    panel, quality["panel"] = make_panel(sales, stores)
    metrics, model, predictions = evaluate(panel, lag)
    metrics["sales_aggregation"] = sales_unit
    predictions["sales_aggregation"] = sales_unit
    predictions["chosen_model"] = model
    predictions = predictions.rename(columns={
        "target": "observed_krw_per_store", "baseline": "baseline_krw_per_store",
    })
    predictions["predicted_krw_per_store"] = predictions[
        "baseline_krw_per_store" if model == "baseline" else model
    ]
    write_table(out, "model_comparison.csv", metrics)
    write_table(out, "predictions.csv", predictions[[
        "quarter", "feature_quarter", "area", "name", "type", "sales_aggregation", "chosen_model",
        "observed_krw_per_store", "predicted_krw_per_store", "baseline_krw_per_store",
        "ridge", "random_forest", "ridge_no_sales", "random_forest_no_sales",
    ]])
    status.update(seoul_model="후향 검증 완료", chosen_model=model, assumed_lag_quarters=lag)
    if area_ready:
        prior_quarter = pd.Period(TEST, freq="Q") - lag
        population_key = f"population-{prior_quarter.year}"
        population = None
        if provenance.get(population_key, {}).get("eligible"):
            population = read_quarters(raw / manifest[population_key]["path"],
                                       "population", prior_quarter.year)
            population = population.loc[population["quarter"].eq(prior_quarter), ["area", "weight"]]
        transaction = transaction_weight(sales, prior_quarter)
        demand, candidates, weights, label, rates = spatial_inputs(
            areas, predictions, "predicted_krw_per_store", population, transaction,
        )
        summary, sites, repeats, maps = compare(demand, candidates, weights, label)
        summary["sales_aggregation"] = sales_unit
        sites["sales_aggregation"] = sales_unit
        write_table(out, "district_join_rates.csv", rates)
        write_table(out, "strategy_summary.csv", summary)
        write_table(out, "strategy_candidates.csv", sites)
        write_table(out, "selection_frequency.csv", repeats)
        draw_map(out / "candidate_map.png", demand, candidates, boundaries, maps,
                 "2022 Q4 forecasts | 2023 area snapshot")
        quality["space"] = {
            "predictions": len(predictions), "matched_predictions": int(rates["candidates"].sum()),
            "district": demand.iloc[0]["district"], "weight_measure": label,
            "weight_observation_quarter": str(prior_quarter), "scenario_count": len(summary),
        }
        status["strategy_comparison"] = "공간 시나리오 검증 완료"
        if label == "historical_foot_traffic":
            status["population_weight"] = "사용"
    else:
        status["strategy_reason"] = "적격한 영역 파일 부재"
    write_json(out, "data_quality.json", quality)
    write_json(out, "run_status.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--manifest", type=Path, default=Path("docs/inputs.json"))
    parser.add_argument("--lag", type=int, default=2)
    parser.add_argument("--download", action="store_true", help="fetch current portal archives")
    parser.add_argument("--require-full", action="store_true", help="exit 2 if analysis is incomplete")
    args = parser.parse_args()
    if args.lag < 2:
        parser.error("--lag must be at least two quarters")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if args.download:
        download(args.raw, manifest)
    status = run(args.raw, args.out, manifest, args.lag)
    print(json.dumps(status, ensure_ascii=True, indent=2))
    return 2 if args.require_full and any(status[stage] == "미실행" for stage in (
        "seoul_model", "strategy_comparison",
    )) else 0


if __name__ == "__main__":
    raise SystemExit(main())
