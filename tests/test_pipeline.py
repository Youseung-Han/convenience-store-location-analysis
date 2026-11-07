from datetime import date
from hashlib import sha256
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile, ZipInfo

import numpy as np
import pandas as pd

from seoul_location.data import audit_source, read_quarters, require_unique
from seoul_location.model import evaluate, lag_panel, make_panel, split
from seoul_location.spatial import compare, coverage_matrix, covered_weight, solve, spatial_inputs


def fixture():
    sales, stores = [], []
    for q, quarter in enumerate(pd.period_range("2021Q1", "2022Q4", freq="Q")):
        for i in range(20):
            common = {"quarter": quarter, "area": str(i), "name": f"area {i}",
                      "type": "A", "industry": "CS300002"}
            sales.append(common | {"sales": 100 * i + 40 * q + 100, "transactions": i})
            stores.append(common | {"stores": (i % 4) + 1, "opened": 1, "closed": 0,
                                    "opening_rate": 1, "closing_rate": 0, "franchise": i % 3})
    return pd.DataFrame(sales), pd.DataFrame(stores)


class SourceTests(unittest.TestCase):
    def test_late_zip_rejected_despite_portal_date(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "late.zip"
            with ZipFile(file, "w") as archive:
                archive.writestr(ZipInfo("source.csv", (2025, 6, 4, 0, 0, 0)), "value")
            entry = {
                "path": file.name, "sha256": sha256(file.read_bytes()).hexdigest(),
                "portal_modified": "2023-10-30", "version_date": "2023-10-30",
                "version_evidence": "unit test",
            }
            report = audit_source(root, entry)
            self.assertFalse(report["eligible"])
            self.assertEqual(report["reason"], "ZIP member timestamp after cutoff")
            revised = audit_source(root, entry, allow_revised=True)
            self.assertTrue(revised["eligible"])
            self.assertEqual(revised["version_policy"], "historical_observations_in_revised_snapshot")
            self.assertFalse(audit_source(root, entry | {"sha256": "wrong"},
                                          allow_revised=True)["eligible"])

    def test_version_requires_matching_hash_and_date(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "archive.csv"
            file.write_bytes(b"example")
            entry = {"path": file.name, "sha256": sha256(file.read_bytes()).hexdigest(),
                     "version_date": date(2024, 4, 30).isoformat(), "version_evidence": "test"}
            self.assertTrue(audit_source(root, entry)["eligible"])
            self.assertFalse(audit_source(root, entry | {"sha256": "wrong"})["eligible"])
            self.assertFalse(audit_source(root, entry | {"version_date": "2024-05-01"})["eligible"])

    def test_old_cp949_csv_inside_zip(self):
        columns = "기준_년_코드,기준_분기_코드,상권_코드,상권_코드_명,상권_구분_코드,서비스_업종_코드,서비스_업종_코드_명,분기당_매출_금액,분기당_매출_건수"
        rows = [f"2021,{q},001,상권,A,CS300002,편의점,500,10" for q in range(1, 5)]
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "sales.zip"
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("sales.csv", "\n".join([columns, *rows]).encode("cp949"))
            sales = read_quarters(archive, "sales", 2021, "quarter_total")
            self.assertEqual(sales["area"].iloc[0], "001")
            self.assertEqual(sales["sales"].sum(), 2000)
            rows[-1] = rows[-1].replace("2021,", "2024,", 1)
            with ZipFile(archive, "w") as zip_file:
                zip_file.writestr("sales.csv", "\n".join([columns, *rows]).encode("cp949"))
            with self.assertRaisesRegex(ValueError, "out-of-year quarter"):
                read_quarters(archive, "sales", 2021, "quarter_total")


    def test_join_key_rejects_duplicates_and_missing(self):
        for codes in (["1", "1"], ["1", None]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                require_unique(pd.DataFrame({"area": codes}), ["area"])

    def test_store_denominator_includes_franchises(self):
        columns = ("기준_년분기_코드,상권_코드,상권_코드_명,상권_구분_코드,서비스_업종_코드,"
                   "서비스_업종_코드_명,점포_수,유사_업종_점포_수,개업_점포_수,폐업_점포_수,"
                   "개업_율,폐업_률,프랜차이즈_점포_수")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stores.csv"
            rows = [f"2021{q},001,상권,A,CS300002,편의점,0,3,0,0,0,0,3" for q in range(1, 5)]
            path.write_text("\n".join([columns, *rows]), encoding="utf-8")
            stores = read_quarters(path, "stores", 2021)
            self.assertTrue(stores["stores"].eq(3).all())
            path.write_text("\n".join([columns, *rows]).replace(",0,3,0,", ",0,4,0,"),
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "total store"):
                read_quarters(path, "stores", 2021)


class TemporalTests(unittest.TestCase):
    def test_zero_store_and_missing_sales_excluded(self):
        sales, stores = fixture()
        stores.loc[0, "stores"] = 0
        sales = sales.drop(index=1)
        panel, qa = make_panel(sales, stores)
        self.assertEqual(panel["target"].isna().sum(), 2)
        self.assertEqual(qa["2021Q1"]["zero_store"], 1)
        self.assertEqual(qa["2021Q1"]["missing_sales"], 1)

    def test_calendar_lag_does_not_shift_across_gaps(self):
        sales, stores = fixture()
        sales = sales.drop(index=0)
        panel, _ = make_panel(sales, stores)
        lagged = lag_panel(panel, 2)
        row = lagged.loc[lagged["area"].eq("0") & lagged["quarter"].eq(pd.Period("2021Q3"))]
        self.assertTrue(row.empty)
        self.assertTrue(lagged["quarter"].eq(lagged["feature_quarter"] + 2).all())

    def test_target_exclusion_does_not_filter_scoring_roster(self):
        sales, stores = fixture()
        quarter = pd.Period("2022Q4")
        sales = sales.loc[~(sales["quarter"].eq(quarter) & sales["area"].eq("0"))]
        stores = stores.loc[~(stores["quarter"].eq(quarter) & stores["area"].eq("0"))]
        panel, _ = make_panel(sales, stores)
        train, score = split(lag_panel(panel, 2), quarter, 2)
        self.assertEqual(train["quarter"].max(), pd.Period("2022Q2"))
        self.assertEqual(len(score), 20)
        self.assertTrue(score.loc[score["area"].eq("0"), "target"].isna().all())

    def test_all_models_use_same_sample_and_test_cannot_choose_model(self):
        sales, stores = fixture()
        panel, _ = make_panel(sales, stores)
        before, selected, _ = evaluate(panel, 2)
        altered = panel.copy()
        altered.loc[altered["quarter"].eq(pd.Period("2022Q4")), "target"] *= 1000
        after, selected_after, _ = evaluate(altered, 2)
        self.assertEqual(selected, selected_after)
        self.assertEqual(len(before), 15)
        self.assertTrue(before.groupby("quarter")["n_evaluated"].nunique().eq(1).all())
        pd.testing.assert_frame_equal(before.iloc[:10], after.iloc[:10])


class SpatialTests(unittest.TestCase):
    def test_exact_radius_is_included(self):
        demand = pd.DataFrame({"x": [0, 300, 301], "y": [0, 400, 400]})
        np.testing.assert_array_equal(coverage_matrix(demand, demand.iloc[:1], 500).ravel(),
                                      [True, True, False])

    def test_overlap_is_counted_once_and_milp_matches_brute_force(self):
        matrix = np.array([[1, 1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0],
                           [0, 0, 0, 1]], dtype=bool)
        weights = np.array([10, 6, 8, 5])
        scores = np.array([20, 12, 2, 21])
        self.assertEqual(covered_weight(matrix, weights, [0, 1]), 16)
        options = list(combinations(range(4), 2))
        b = solve(matrix, weights, scores, 2)
        max_weight = max(covered_weight(matrix, weights, combo) for combo in options)
        self.assertEqual(covered_weight(matrix, weights, b), max_weight)
        for fraction in (0.9, 0.95, 1):
            floor = fraction * max_weight
            c = solve(matrix, weights, scores, 2, floor)
            brute_score = max(sum(scores[list(combo)]) for combo in options
                              if covered_weight(matrix, weights, combo) >= floor)
            self.assertEqual(sum(scores[c]), brute_score)

    def test_sensitivity_grid_and_candidate_filter(self):
        areas = pd.DataFrame({"area": [str(i) for i in range(12)], "type": "A", "name": "name",
                              "district": "district", "district_code": "1",
                              "x": np.arange(12) * 250, "y": 0})
        scored = areas.iloc[:11].assign(baseline=np.arange(11))
        weights = areas[["area"]].assign(weight=np.arange(1, 13))
        demand, candidates, weight, label, _ = spatial_inputs(areas, scored, "baseline", None, weights)
        self.assertEqual(len(demand), 12)
        self.assertEqual(len(candidates), 11)
        self.assertEqual(label, "historical_non_convenience_transactions")
        summary, sites, repeats, maps = compare(demand, candidates, weight, label)
        self.assertEqual(len(summary), 45)
        self.assertEqual(set(maps), {"A", "B", "C"})
        self.assertEqual(len(sites), int(summary["site_count"].sum()))
        self.assertEqual(repeats["selection_count"].sum(), len(sites))
        compromise = summary.loc[summary["strategy"].eq("C")]
        self.assertTrue((compromise["covered_weight"] + 1e-7 >= compromise["maximum_weight"]
                         * compromise["coverage_floor_fraction_of_B"]).all())
