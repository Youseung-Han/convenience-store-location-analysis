"""Validate official representative points and solve discrete coverage scenarios."""

from io import BytesIO
from zipfile import ZipFile

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.spatial.distance import cdist
import shapefile

from .data import require_unique


def read_areas(path):
    with ZipFile(path) as archive:
        contents = {}
        for suffix in ("shp", "shx", "dbf", "prj", "cpg"):
            members = [name for name in archive.namelist() if name.lower().endswith("." + suffix)]
            if len(members) != 1:
                raise ValueError(f"{path.name}: expected exactly one .{suffix}")
            contents[suffix] = archive.read(members[0])
    crs = CRS.from_wkt(contents["prj"].decode("ascii"))
    if crs.to_epsg() != 5181 or any(axis.unit_name != "metre" for axis in crs.axis_info):
        raise ValueError("expected metre-based EPSG:5181")
    rows = []
    boundaries = {}
    with shapefile.Reader(
        shp=BytesIO(contents["shp"]), shx=BytesIO(contents["shx"]),
        dbf=BytesIO(contents["dbf"]), encoding=contents["cpg"].decode().strip(),
    ) as reader:
        for record in reader.iterShapeRecords():
            fields = record.record.as_dict()
            area = fields["TRDAR_CD"]
            shape = record.shape
            points = np.asarray(shape.points, dtype=float)
            parts = [*shape.parts, len(points)]
            boundaries[area] = [points[a:b] for a, b in zip(parts, parts[1:])]
            rows.append({
                "area": area, "type": fields["TRDAR_SE_C"], "name": fields["TRDAR_CD_N"],
                "district": fields["SIGNGU_CD_"], "district_code": fields["SIGNGU_CD"],
                "x": fields["XCNTS_VALU"], "y": fields["YDNTS_VALU"],
                "point_inside_shape_bbox": (
                    shape.bbox[0] <= fields["XCNTS_VALU"] <= shape.bbox[2]
                    and shape.bbox[1] <= fields["YDNTS_VALU"] <= shape.bbox[3]
                ),
            })
    frame = pd.DataFrame(rows).sort_values("area").reset_index(drop=True)
    require_unique(frame, ["area"])
    lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(
        frame["x"].to_numpy(), frame["y"].to_numpy(),
    )
    if not (np.isfinite(frame[["x", "y"]]).all(axis=None)
            and np.all((126.7 < lon) & (lon < 127.3) & (37.4 < lat) & (lat < 37.8))):
        raise ValueError("invalid or out-of-Seoul representative point")
    if frame["district_code"].nunique() != 25:
        raise ValueError("expected all 25 Seoul districts")
    return frame, boundaries


def coverage_matrix(demand, candidates, radius):
    return cdist(demand[["x", "y"]], candidates[["x", "y"]]) <= radius


def covered_weight(matrix, weights, selected):
    return float(weights[matrix[:, selected].any(axis=1)].sum())


def solve(matrix, weights, scores, count, floor=None):
    """For B maximize weights, or for C maximize scores subject to the floor."""
    demand, candidates = matrix.shape
    if not 0 < count <= candidates:
        raise ValueError("infeasible selection count")
    pick = np.r_[np.ones(candidates), np.zeros(demand)]
    coverage = np.r_[np.zeros(candidates), weights]
    links = np.c_[-matrix.astype(float), np.eye(demand)]
    constraints = [
        LinearConstraint(pick, count, count),
        LinearConstraint(links, -np.inf, 0),
    ]
    if floor is None:
        objective = coverage / weights.sum()
    else:
        constraints.append(LinearConstraint(coverage, floor, np.inf))
        objective = np.r_[scores / max(np.abs(scores).max(), 1), np.zeros(demand)]
    result = milp(
        -objective, integrality=np.ones(demand + candidates),
        bounds=Bounds(0, 1), constraints=constraints, options={"mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"MILP failed: {result.message}")
    chosen = np.flatnonzero(result.x[:candidates] > 0.5)
    if len(chosen) != count or (
        floor is not None and covered_weight(matrix, weights, chosen) < floor - 1e-7
    ):
        raise RuntimeError("solution violates a selection or coverage constraint")
    return chosen


def spatial_inputs(areas, scored, model, population, transactions):
    joined = areas.merge(scored[["area", "type", model]], on=["area", "type"],
                         how="left", validate="one_to_one")
    joined = joined.rename(columns={model: "predicted_krw_per_store"})
    rates = joined.assign(joined=joined["predicted_krw_per_store"].notna()).groupby(
        ["district_code", "district"], as_index=False,
    ).agg(area_points=("area", "size"), candidates=("joined", "sum"))
    rates["join_rate"] = rates["candidates"] / rates["area_points"]
    rates = rates.sort_values(["join_rate", "candidates", "district_code"],
                              ascending=[False, False, True])
    feasible = rates.loc[rates["candidates"].ge(10)]
    if feasible.empty:
        raise ValueError("no district supports the largest requested scenario")
    district_code = feasible.iloc[0]["district_code"]
    demand = joined.loc[joined["district_code"].eq(district_code)].copy()
    candidates = demand.loc[demand["predicted_krw_per_store"].notna()].copy()
    for source, label in [(population, "historical_foot_traffic"),
                          (transactions, "historical_non_convenience_transactions")]:
        if source is not None:
            aligned = demand[["area"]].merge(source, on="area", how="left", validate="one_to_one")
            weights = aligned["weight"].to_numpy(dtype=float)
            if np.isfinite(weights).all() and (weights >= 0).all() and weights.sum() > 0:
                return demand, candidates, weights, label, rates
    return demand, candidates, np.ones(len(demand)), "equal_area_points", rates


def compare(demand, candidates, weights, label):
    scores = candidates["predicted_krw_per_store"].to_numpy()
    order = np.lexsort((candidates["area"], -scores))
    scenarios = []
    selections = []
    maps = {}
    for radius in (300, 500, 700):
        matrix = coverage_matrix(demand, candidates, radius)
        for count in (3, 5, 10):
            coverage_optimum = solve(matrix, weights, scores, count)
            maximum = covered_weight(matrix, weights, coverage_optimum)
            # Break B's coverage ties by maximizing predicted sales at full coverage.
            best = solve(matrix, weights, scores, count, maximum)
            options = [("A", None, order[:count]), ("B", None, best)]
            options.extend(
                ("C", fraction, best if fraction == 1 else
                 solve(matrix, weights, scores, count, maximum * fraction))
                for fraction in (0.90, 0.95, 1.0)
            )
            for strategy, fraction, selected in options:
                covered = matrix[:, selected].any(axis=1)
                weight = float(weights[covered].sum())
                floor = None if fraction is None else maximum * fraction
                if len(set(selected)) != count or (floor is not None and weight < floor - 1e-7):
                    raise RuntimeError("invalid scenario selection")
                row = {
                    "strategy": strategy, "radius_m": radius, "site_count": count,
                    "coverage_floor_fraction_of_B": fraction, "district": demand.iloc[0]["district"],
                    "weight_measure": label, "covered_points": int(covered.sum()),
                    "demand_points": len(demand), "covered_weight": weight,
                    "total_weight": weights.sum(), "maximum_weight": maximum,
                    "coverage_pct": 100 * weight / weights.sum(),
                    "predicted_sum_krw_per_store": scores[selected].sum(),
                }
                scenarios.append(row)
                for _, site in candidates.iloc[selected].iterrows():
                    selections.append(row | site[["area", "name", "predicted_krw_per_store"]].to_dict())
                if radius == 500 and count == 5 and fraction in (None, 0.95):
                    maps[strategy] = (candidates.iloc[selected], covered)
    sites = pd.DataFrame(selections)
    repeat = sites.groupby(["strategy", "area", "name"], as_index=False).size()
    repeat = repeat.rename(columns={"size": "selection_count"})
    return pd.DataFrame(scenarios), sites, repeat, maps


def draw_map(path, demand, candidates, boundaries, maps, caption, radius=500):
    fig, axes = plt.subplots(1, len(maps), figsize=(5 * len(maps), 5.9), squeeze=False)
    for axis, (label, (selected, covered)) in zip(axes[0], maps.items()):
        lines = [line for code in demand["area"] for line in boundaries[code]]
        axis.add_collection(LineCollection(lines, color="#a9bec4", linewidth=0.5, zorder=1))
        for site in selected.itertuples():
            axis.add_patch(Circle((site.x, site.y), radius, fc="#7b9ce9",
                                  ec="#3159a5", alpha=0.19, lw=1, zorder=2))
        axis.scatter(demand["x"], demand["y"], s=13, color="#748794", zorder=3, label="Demand point")
        axis.scatter(demand.loc[covered, "x"], demand.loc[covered, "y"],
                     s=16, color="#008785", zorder=4, label="Covered point")
        axis.scatter(candidates["x"], candidates["y"], marker="+", s=22,
                     color="#345975", zorder=5, label="Candidate")
        axis.scatter(selected["x"], selected["y"], marker="*", s=103,
                     color="#d96828", edgecolor="white", linewidth=0.6, zorder=6, label="Selected")
        axis.set_title(label, fontweight="bold")
        axis.set_aspect("equal")
        axis.set_xlim(demand["x"].min() - 650, demand["x"].max() + 650)
        axis.set_ylim(demand["y"].min() - 650, demand["y"].max() + 650)
        axis.ticklabel_format(style="plain", useOffset=False)
        axis.tick_params(labelsize=7)
        axis.set_xlabel("EPSG:5181 easting (m)")
        axis.set_ylabel("Northing (m)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2 if len(maps) == 1 else 4,
               frameon=False, bbox_to_anchor=(0.5, 0.088), fontsize=8)
    fig.suptitle(caption, y=0.97, fontsize=14, fontweight="bold")
    fig.text(0.5, 0.045, f"Circles show {radius} m straight-line reach", ha="center", fontsize=8)
    fig.text(0.5, 0.02, "Source: Seoul Metropolitan Government, OA-15560 (KOGL Type 1)",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.18, 1, 0.93))
    fig.savefig(path, dpi=160)
    plt.close(fig)
