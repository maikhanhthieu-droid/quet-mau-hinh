"""Audit publication-quality tiers for Triangle Family scanners.

This script does not choose a new detector rule. It stress-tests the current
Triangle output along the four checks needed before using the tier in a public
chapter:

* tier-threshold sensitivity,
* target-family behavior by tier,
* overlap/cooldown sensitivity,
* seeded visual review samples by tier.
* cluster bootstrap by symbol, temporal split, and regime-liquidity interaction.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bear_flag_db_source_parity_audit import DEFAULT_DB  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/triangle_publication_quality_audit")
TARGET_BANDS = (0.5, 0.75, 1.0)
TIER_ORDER = ("premium", "standard", "loose", "data_limited")

PATTERN_META = {
    "triangles_ascending": {
        "title": "Ascending Triangle",
        "vietnamese_title": "Tam giác tăng",
        "audit_id": "ascending_triangle_publication_quality_audit_v1",
        "line_level_field": "triangle_resistance",
        "line_level_label": "kháng cự",
    },
    "triangles_descending": {
        "title": "Descending Triangle",
        "vietnamese_title": "Tam giác giảm",
        "audit_id": "descending_triangle_publication_quality_audit_v1",
        "line_level_field": "triangle_support",
        "line_level_label": "hỗ trợ",
    },
    "triangles_symmetrical": {
        "title": "Symmetrical Triangle",
        "vietnamese_title": "Tam giác cân",
        "audit_id": "symmetrical_triangle_publication_quality_audit_v1",
        "line_level_field": "triangle_resistance",
        "line_level_label": "biên tam giác",
    },
    "wedges_falling": {
        "title": "Falling Wedge",
        "vietnamese_title": "Nêm giảm",
        "audit_id": "falling_wedge_publication_quality_audit_v1",
        "line_level_field": "triangle_resistance",
        "line_level_label": "biên nêm",
    },
    "wedges_rising": {
        "title": "Rising Wedge",
        "vietnamese_title": "Nêm tăng",
        "audit_id": "rising_wedge_publication_quality_audit_v1",
        "line_level_field": "triangle_support",
        "line_level_label": "biên nêm",
    },
}


def _infer_pattern_id(events: pd.DataFrame) -> str:
    for column in ("pattern_key", "pattern_id"):
        if column in events.columns:
            values = events[column].dropna().astype(str)
            if not values.empty:
                return str(values.mode().iloc[0])
    variant_values = events.get("variant", pd.Series(dtype=str)).dropna().astype(str)
    if not variant_values.empty:
        if variant_values.str.contains("descending", case=False, na=False).any():
            return "triangles_descending"
        if variant_values.str.contains("symmetrical", case=False, na=False).any():
            return "triangles_symmetrical"
        if variant_values.str.contains("falling_wedge|falling wedge", case=False, na=False).any():
            return "wedges_falling"
        if variant_values.str.contains("rising_wedge|rising wedge", case=False, na=False).any():
            return "wedges_rising"
    return "triangles_ascending"


def _pattern_meta(pattern_id: str) -> Dict[str, str]:
    return dict(PATTERN_META.get(pattern_id) or PATTERN_META["triangles_ascending"])


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _pct(num: float, den: float) -> Optional[float]:
    if den <= 0:
        return None
    return round(float(num) / float(den) * 100.0, 2)


def _median(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if series.empty:
        return None
    return round(float(series.median()), 2)


def _wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> Dict[str, Optional[float]]:
    if total <= 0:
        return {"low": None, "high": None, "half_width": None}
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4 * total)) / total) / denom
    low = max(0.0, centre - margin) * 100.0
    high = min(1.0, centre + margin) * 100.0
    return {"low": round(low, 2), "high": round(high, 2), "half_width": round((high - low) / 2.0, 2)}


def _as_bool(series: pd.Series) -> pd.Series:
    if series.empty:
        return series.astype(bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _load_events(path: Path) -> pd.DataFrame:
    events = pd.read_csv(path)
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for column in (
        "target_hit",
        "failure_5pct",
        "target_first_before_adverse_5pct",
        "volume_confirmed",
        "is_primary_event_60d",
    ):
        if column in events.columns:
            events[column] = _as_bool(events[column])
    for column in (
        "target_dist_pct",
        "mfe_pct",
        "mae_pct",
        "publication_quality_score",
        "pattern_quality_score",
    ):
        if column in events.columns:
            events[column] = pd.to_numeric(events[column], errors="coerce")
    events["breakout_ts"] = pd.to_datetime(events.get("breakout_date"), errors="coerce")
    return events


def _load_path(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(["event_id", "bar_after_breakout"]).copy()
    return frame


def _target_path_flags(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float, horizon: int = 120) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["event_id", "target_hit_band", "target_first_band", "days_to_target_band"])
    target_dist = events[["event_id", "target_dist_pct"]].copy()
    target_dist["target_threshold_pct"] = pd.to_numeric(target_dist["target_dist_pct"], errors="coerce") * float(target_multiple)
    working = path[path["bar_after_breakout"].between(1, int(horizon), inclusive="both")].merge(target_dist, on="event_id", how="inner")
    rows: List[Dict[str, Any]] = []
    for event_id, group in working.groupby("event_id", sort=False):
        threshold = pd.to_numeric(group["target_threshold_pct"], errors="coerce").dropna()
        if threshold.empty:
            continue
        target_level = float(threshold.iloc[0])
        days_to_target: Optional[int] = None
        days_to_adverse: Optional[int] = None
        for row in group.sort_values("bar_after_breakout").itertuples(index=False):
            bar = int(getattr(row, "bar_after_breakout"))
            high_exc = float(getattr(row, "signed_high_excursion_pct"))
            low_exc = float(getattr(row, "signed_low_excursion_pct"))
            if days_to_target is None and high_exc >= target_level:
                days_to_target = bar
            if days_to_adverse is None and low_exc <= -5.0:
                days_to_adverse = bar
        target_hit = days_to_target is not None
        target_first = bool(target_hit and (days_to_adverse is None or int(days_to_target) < int(days_to_adverse)))
        rows.append(
            {
                "event_id": event_id,
                "target_hit_band": bool(target_hit),
                "target_first_band": target_first,
                "days_to_target_band": int(days_to_target) if days_to_target is not None else None,
            }
        )
    flags = pd.DataFrame(rows)
    return events[["event_id"]].merge(flags, on="event_id", how="left").fillna({"target_hit_band": False, "target_first_band": False})


def _target_role(target_multiple: float) -> str:
    if abs(float(target_multiple) - 0.5) < 1e-9:
        return "local_base"
    if abs(float(target_multiple) - 0.75) < 1e-9:
        return "local_stretch"
    if abs(float(target_multiple) - 1.0) < 1e-9:
        return "legacy_full_height"
    return "sensitivity"


def _metrics(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float = 1.0, row_id: str = "all") -> Dict[str, Any]:
    events = events.copy()
    flags = _target_path_flags(events, path, target_multiple=target_multiple)
    events = events.merge(flags, on="event_id", how="left")
    n = int(len(events))
    hit = int(events["target_hit_band"].fillna(False).sum()) if "target_hit_band" in events.columns else 0
    first = int(events["target_first_band"].fillna(False).sum()) if "target_first_band" in events.columns else 0
    failure = int(events.get("failure_5pct", pd.Series(False, index=events.index)).fillna(False).sum())
    med_mfe = _median(events.get("mfe_pct", []))
    med_mae = _median(events.get("mae_pct", []))
    return {
        "row_id": row_id,
        "target_multiple": float(target_multiple),
        "target_role": _target_role(target_multiple),
        "n": n,
        "target_hit_rate_pct": _pct(hit, n),
        "target_hit_wilson": _wilson_interval(hit, n),
        "target_first_before_adverse_5pct_rate_pct": _pct(first, n),
        "target_first_wilson": _wilson_interval(first, n),
        "failure_5pct_rate_pct": _pct(failure, n),
        "median_mfe_pct": med_mfe,
        "median_mae_pct": med_mae,
        "mfe_mae_median_ratio": round(float(med_mfe) / max(float(med_mae), 1.0), 2) if med_mfe is not None and med_mae is not None else None,
    }


def _tier_target_table(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tier in TIER_ORDER:
        subset = events[events["publication_quality_tier"].astype(str) == tier].copy()
        for target_multiple in TARGET_BANDS:
            rows.append({"tier": tier, **_metrics(subset, path, target_multiple=target_multiple, row_id=tier)})
    for target_multiple in TARGET_BANDS:
        rows.append({"tier": "premium+standard", **_metrics(events[events["publication_quality_tier"].isin(["premium", "standard"])], path, target_multiple=target_multiple, row_id="premium+standard")})
        rows.append({"tier": "all", **_metrics(events, path, target_multiple=target_multiple, row_id="all")})
    return rows


def _assign_threshold_variant(
    events: pd.DataFrame,
    *,
    standard_cut: float,
    premium_cut: float,
    high_spread_max: float,
    low_rise_min: float,
    compression_max: float,
) -> pd.Series:
    score = pd.to_numeric(events.get("publication_quality_score"), errors="coerce").fillna(0.0)
    current = events.get("publication_quality_tier", pd.Series("unknown", index=events.index)).astype(str)
    path = events.get("path_quality_bucket", pd.Series("unknown", index=events.index)).astype(str)
    tradability = events.get("tradability_quality_bucket", pd.Series("unknown", index=events.index)).astype(str)
    high_spread = pd.to_numeric(events.get("high_spread_pct"), errors="coerce")
    low_rise = pd.to_numeric(events.get("low_rise_pct"), errors="coerce")
    compression = pd.to_numeric(events.get("compression_ratio"), errors="coerce")
    breakout_clearance = pd.to_numeric(events.get("breakout_clearance_pct"), errors="coerce")
    height = pd.to_numeric(events.get("pattern_height_pct"), errors="coerce")
    volume = pd.to_numeric(events.get("breakout_volume_ratio"), errors="coerce")
    out = pd.Series("loose", index=events.index, dtype=object)
    out[current == "data_limited"] = "data_limited"
    eligible = current != "data_limited"
    out[eligible & (score >= float(standard_cut))] = "standard"
    premium_mask = (
        eligible
        & (score >= float(premium_cut))
        & (path == "clean")
        & (tradability == "clean")
        & (high_spread <= float(high_spread_max))
        & (low_rise >= float(low_rise_min))
        & (compression <= float(compression_max))
        & (breakout_clearance >= 1.20)
        & height.between(7.0, 25.0, inclusive="both")
        & (volume >= 0.80)
    )
    out[premium_mask] = "premium"
    return out


def _tier_threshold_sensitivity(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    variants = [
        ("lenient", 60.0, 75.0, 1.20, 4.0, 0.65),
        ("base", 65.0, 80.0, 1.00, 5.0, 0.60),
        ("strict", 70.0, 85.0, 0.80, 6.0, 0.55),
    ]
    rows: List[Dict[str, Any]] = []
    for variant, standard_cut, premium_cut, high_spread_max, low_rise_min, compression_max in variants:
        scoped = events.copy()
        scoped["tier_variant"] = _assign_threshold_variant(
            scoped,
            standard_cut=standard_cut,
            premium_cut=premium_cut,
            high_spread_max=high_spread_max,
            low_rise_min=low_rise_min,
            compression_max=compression_max,
        )
        for tier in TIER_ORDER:
            subset = scoped[scoped["tier_variant"] == tier].copy()
            rows.append(
                {
                    "variant": variant,
                    "standard_cut": standard_cut,
                    "premium_cut": premium_cut,
                    "premium_high_spread_max": high_spread_max,
                    "premium_low_rise_min": low_rise_min,
                    "premium_compression_max": compression_max,
                    "tier": tier,
                    **_metrics(subset, path, target_multiple=0.5, row_id=f"{variant}:{tier}"),
                }
            )
    return rows


def _cooldown_events(events: pd.DataFrame, days: int) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    working = events.dropna(subset=["breakout_ts"]).sort_values(["symbol", "breakout_ts", "event_id"]).copy()
    keep: List[int] = []
    last_by_symbol: Dict[str, pd.Timestamp] = {}
    for idx, row in working.iterrows():
        symbol = str(row.get("symbol") or "")
        breakout_ts = pd.Timestamp(row["breakout_ts"])
        last = last_by_symbol.get(symbol)
        if last is None or (breakout_ts - last).days >= int(days):
            keep.append(idx)
            last_by_symbol[symbol] = breakout_ts
    return events.loc[keep].copy()


def _one_event_per_symbol(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    working = events.dropna(subset=["breakout_ts"]).sort_values(["symbol", "breakout_ts", "event_id"]).copy()
    return working.drop_duplicates("symbol").copy()


def _overlap_sensitivity(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    scopes = [
        ("all", events),
        ("premium+standard", events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()),
    ]
    rows: List[Dict[str, Any]] = []
    for scope_name, scoped in scopes:
        variants = [
            ("base", scoped),
            ("cooldown_20d", _cooldown_events(scoped, 20)),
            ("cooldown_40d", _cooldown_events(scoped, 40)),
            ("cooldown_60d", _cooldown_events(scoped, 60)),
            ("cooldown_90d", _cooldown_events(scoped, 90)),
            ("one_event_per_symbol", _one_event_per_symbol(scoped)),
        ]
        base_n = max(len(scoped), 1)
        for variant, subset in variants:
            rows.append(
                {
                    "scope": scope_name,
                    "variant": variant,
                    "retention_pct": round(len(subset) / base_n * 100.0, 2),
                    **_metrics(subset, path, target_multiple=0.5, row_id=f"{scope_name}:{variant}"),
                }
            )
    return rows


def _cluster_resample_events(events: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    if events.empty or "symbol" not in events.columns:
        return events.copy()
    symbols = events["symbol"].dropna().astype(str).unique()
    if len(symbols) < 2:
        return events.copy()
    sampled_symbols = rng.choice(symbols, size=len(symbols), replace=True)
    parts: List[pd.DataFrame] = []
    for draw_id, symbol in enumerate(sampled_symbols):
        part = events[events["symbol"].astype(str) == str(symbol)].copy()
        part["_cluster_draw_id"] = draw_id
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else events.iloc[:0].copy()


def _symbol_value_groups(events: pd.DataFrame, columns: Sequence[str]) -> Dict[str, np.ndarray]:
    groups: Dict[str, np.ndarray] = {}
    if events.empty or "symbol" not in events.columns:
        return groups
    for symbol, group in events.groupby("symbol", dropna=True):
        values = group[list(columns)].copy()
        for column in columns:
            if values[column].dtype == bool:
                values[column] = values[column].astype(float)
            else:
                values[column] = pd.to_numeric(values[column], errors="coerce")
        arr = values.dropna().to_numpy(dtype=float)
        if len(arr):
            groups[str(symbol)] = arr
    return groups


def _cluster_bool_rate_ci(events: pd.DataFrame, column: str, *, seed: int, reps: int = 600) -> Dict[str, Optional[float]]:
    if events.empty or events["symbol"].nunique() < 2:
        return {"low": None, "high": None, "half_width": None}
    groups = _symbol_value_groups(events, [column])
    symbols = np.array(list(groups.keys()))
    if len(symbols) < 2:
        return {"low": None, "high": None, "half_width": None}
    rng = np.random.default_rng(seed)
    stats = np.empty(int(reps), dtype=float)
    for i in range(int(reps)):
        sampled = rng.choice(symbols, size=len(symbols), replace=True)
        values = [groups[str(symbol)][:, 0] for symbol in sampled if str(symbol) in groups]
        if not values:
            stats[i] = np.nan
        else:
            stats[i] = float(np.concatenate(values).mean() * 100.0)
    stats = stats[np.isfinite(stats)]
    if len(stats) < 5:
        return {"low": None, "high": None, "half_width": None}
    low, high = np.percentile(stats, [2.5, 97.5])
    return {"low": round(float(low), 2), "high": round(float(high), 2), "half_width": round(float((high - low) / 2.0), 2)}


def _cluster_bootstrap_ci(events: pd.DataFrame, column: str, *, seed: int, reps: int = 600) -> Dict[str, Optional[float]]:
    if events.empty or events["symbol"].nunique() < 2 or column not in events.columns:
        return {"low": None, "high": None, "half_width": None}
    groups = _symbol_value_groups(events, [column])
    symbols = np.array(list(groups.keys()))
    if len(symbols) < 2:
        return {"low": None, "high": None, "half_width": None}
    rng = np.random.default_rng(seed)
    stats = np.empty(int(reps), dtype=float)
    for i in range(int(reps)):
        sampled = rng.choice(symbols, size=len(symbols), replace=True)
        values = [groups[str(symbol)][:, 0] for symbol in sampled if str(symbol) in groups]
        stats[i] = float(np.median(np.concatenate(values))) if values else np.nan
    stats = stats[np.isfinite(stats)]
    if len(stats) < 5:
        return {"low": None, "high": None, "half_width": None}
    low, high = np.percentile(stats, [2.5, 97.5])
    return {"low": round(float(low), 2), "high": round(float(high), 2), "half_width": round(float((high - low) / 2.0), 2)}


def _cluster_bootstrap_ratio_ci(events: pd.DataFrame, *, seed: int, reps: int = 600) -> Dict[str, Optional[float]]:
    pairs = events[["mfe_pct", "mae_pct"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(pairs) < 5 or events["symbol"].nunique() < 2:
        return {"low": None, "high": None, "half_width": None}
    groups = _symbol_value_groups(events, ["mfe_pct", "mae_pct"])
    symbols = np.array(list(groups.keys()))
    if len(symbols) < 2:
        return {"low": None, "high": None, "half_width": None}
    rng = np.random.default_rng(seed)
    stats = np.empty(int(reps), dtype=float)
    for i in range(int(reps)):
        sampled = rng.choice(symbols, size=len(symbols), replace=True)
        parts = [groups[str(symbol)] for symbol in sampled if str(symbol) in groups]
        values = np.vstack(parts) if parts else np.empty((0, 2))
        stats[i] = float(np.median(values[:, 0]) / max(float(np.median(values[:, 1])), 1.0)) if len(values) else np.nan
    stats = stats[np.isfinite(stats)]
    if len(stats) < 5:
        return {"low": None, "high": None, "half_width": None}
    low, high = np.percentile(stats, [2.5, 97.5])
    return {"low": round(float(low), 2), "high": round(float(high), 2), "half_width": round(float((high - low) / 2.0), 2)}


def _precision_rows(events: pd.DataFrame, path: pd.DataFrame, *, seed: int) -> List[Dict[str, Any]]:
    scopes = [
        ("all", events),
        ("premium+standard", events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()),
        ("premium", events[events["publication_quality_tier"].astype(str) == "premium"].copy()),
        ("standard", events[events["publication_quality_tier"].astype(str) == "standard"].copy()),
        ("data_limited", events[events["publication_quality_tier"].astype(str) == "data_limited"].copy()),
    ]
    rows: List[Dict[str, Any]] = []
    for offset, (scope, subset) in enumerate(scopes):
        row = _metrics(subset, path, target_multiple=0.5, row_id=scope)
        flags = _target_path_flags(subset, path, target_multiple=0.5)
        prepared = subset.merge(flags, on="event_id", how="left")
        row.update(
            {
                "scope": scope,
                "bootstrap_method": "symbol_cluster",
                "cluster_count": int(subset["symbol"].nunique()) if "symbol" in subset.columns else None,
                "target_hit_cluster_ci": _cluster_bool_rate_ci(prepared, "target_hit_band", seed=seed + offset * 7),
                "target_first_cluster_ci": _cluster_bool_rate_ci(prepared, "target_first_band", seed=seed + offset * 9),
                "median_mfe_bootstrap_ci": _cluster_bootstrap_ci(subset, "mfe_pct", seed=seed + offset * 11),
                "median_mae_bootstrap_ci": _cluster_bootstrap_ci(subset, "mae_pct", seed=seed + offset * 17),
                "mfe_mae_ratio_bootstrap_ci": _cluster_bootstrap_ratio_ci(subset, seed=seed + offset * 23),
            }
        )
        rows.append(row)
    return rows


def _subgroup_robustness(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    rows: List[Dict[str, Any]] = []
    for column, label in (
        ("liquidity_bucket", "liquidity"),
        ("market_regime", "regime"),
        ("market_group", "market_group"),
    ):
        if column not in scoped.columns:
            continue
        for value, group in scoped.groupby(column, dropna=False):
            rows.append(
                {
                    "dimension": label,
                    "bucket": str(value),
                    **_metrics(group.copy(), path, target_multiple=0.5, row_id=f"{label}:{value}"),
                }
            )
    return rows


def _temporal_split_rows(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].dropna(subset=["breakout_ts"]).copy()
    if scoped.empty:
        return []
    scoped["breakout_year"] = scoped["breakout_ts"].dt.year.astype(int)
    rows: List[Dict[str, Any]] = []
    for period, group in scoped.groupby(pd.cut(scoped["breakout_year"], bins=[0, 2015, 2019, 2023, 9999], labels=["<=2015", "2016-2019", "2020-2023", "2024+"]), observed=False):
        if group.empty:
            continue
        rows.append({"split_type": "calendar_period", "period": str(period), **_metrics(group.copy(), path, target_multiple=0.5, row_id=f"period:{period}")})
    quantiles = scoped["breakout_ts"].quantile([0.0, 1 / 3, 2 / 3, 1.0])
    labels = ["early_third", "middle_third", "late_third"]
    for i, label in enumerate(labels):
        left = quantiles.iloc[i]
        right = quantiles.iloc[i + 1]
        if i == 0:
            group = scoped[(scoped["breakout_ts"] >= left) & (scoped["breakout_ts"] <= right)].copy()
        else:
            group = scoped[(scoped["breakout_ts"] > left) & (scoped["breakout_ts"] <= right)].copy()
        if group.empty:
            continue
        row = _metrics(group, path, target_multiple=0.5, row_id=f"temporal:{label}")
        row.update(
            {
                "split_type": "sample_thirds",
                "period": label,
                "start_date": str(group["breakout_ts"].min().date()),
                "end_date": str(group["breakout_ts"].max().date()),
            }
        )
        rows.append(row)
    return rows


def _regime_liquidity_interaction(events: pd.DataFrame, path: pd.DataFrame) -> List[Dict[str, Any]]:
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    if scoped.empty or "market_regime" not in scoped.columns or "liquidity_bucket" not in scoped.columns:
        return []
    rows: List[Dict[str, Any]] = []
    for (regime, liquidity), group in scoped.groupby(["market_regime", "liquidity_bucket"], dropna=False):
        row = _metrics(group.copy(), path, target_multiple=0.5, row_id=f"{regime}:{liquidity}")
        row.update({"market_regime": str(regime), "liquidity_bucket": str(liquidity)})
        rows.append(row)
    return rows


def _load_symbol_ohlcv(db_path: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            "SELECT time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 20, post_bars: int = 40) -> tuple[pd.DataFrame, int]:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy(), 0
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    left = max(0, start_idx - pre_bars)
    right = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[left:right].copy().reset_index(drop=True), left


def _draw_event(ax: plt.Axes, df: pd.DataFrame, event: Mapping[str, Any], offset: int) -> None:
    if df.empty:
        ax.axis("off")
        return
    x = np.arange(len(df))
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.55, alpha=0.72)
        ax.add_patch(
            Rectangle(
                (i - 0.30, min(o, c)),
                0.60,
                max(abs(c - o), 1e-6),
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
                alpha=0.88,
            )
        )
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.8, alpha=0.25)

    formation_start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    formation_end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> Optional[int]:
        if pd.isna(ts):
            return None
        j = int(df["date"].searchsorted(ts, side="left"))
        return min(max(j, 0), len(df) - 1)

    i0, i1, ib = ix(formation_start), ix(formation_end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.0)
    direction = str(event.get("breakout_direction") or "").lower()
    if direction == "down":
        primary_level = event.get("triangle_support")
        primary_color = "#54A24B"
    else:
        primary_level = event.get("triangle_resistance")
        primary_color = "#E45756"
    for price, color, style in (
        (primary_level, primary_color, "-"),
        (event.get("target_price"), "#F58518", "--"),
    ):
        try:
            if price is not None and math.isfinite(float(price)):
                ax.axhline(float(price), color=color, linestyle=style, linewidth=0.8, alpha=0.85)
        except (TypeError, ValueError):
            pass

    def draw_trendline(prefix: str, color: str) -> None:
        if i0 is None:
            formation_x = list(range(len(df)))
        else:
            trend_end = max(v for v in (i1, ib, i0) if v is not None)
            formation_x = [i for i in range(len(df)) if i0 <= i <= trend_end]
        if not formation_x:
            return
        try:
            idx0 = int(event.get(f"triangle_{prefix}_idx0"))
            price0 = float(event.get(f"triangle_{prefix}_price0"))
            slope = float(event.get(f"triangle_{prefix}_slope_per_bar"))
            y = [price0 + slope * ((i + offset) - idx0) for i in formation_x]
            ax.plot(formation_x, y, color=color, linewidth=0.8, alpha=0.9)
        except (TypeError, ValueError):
            return

    draw_trendline("upper", "#E45756")
    draw_trendline("lower", "#54A24B")

    title = (
        f"{event.get('symbol')} {event.get('breakout_date')}\n"
        f"{event.get('publication_quality_tier')} score={event.get('publication_quality_score')} "
        f"MFE/MAE={event.get('mfe_pct')}/{event.get('mae_pct')}"
    )
    ax.set_title(title, fontsize=8)
    ax.grid(alpha=0.15)
    ax.tick_params(axis="both", labelsize=7)


def _visual_audit(events: pd.DataFrame, *, db_path: Path, out_dir: Path, sample_per_tier: int, seed: int, pattern_title: str) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    visual_dir = out_dir / "visual_review_by_tier"
    visual_dir.mkdir(parents=True, exist_ok=True)
    sample_rows: List[Dict[str, Any]] = []
    sheets: Dict[str, str] = {}
    for tier in TIER_ORDER:
        subset = events[events["publication_quality_tier"].astype(str) == tier].copy()
        if subset.empty:
            continue
        chosen_idx = rng.choice(subset.index.to_numpy(), size=min(sample_per_tier, len(subset)), replace=False)
        chosen = subset.loc[chosen_idx].sort_values(["symbol", "breakout_date"]).copy()
        cols = 2
        rows = int(math.ceil(len(chosen) / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(12, max(4, rows * 3.0)), dpi=150)
        axes_array = np.atleast_1d(axes).reshape(rows, cols)
        for ax in axes_array.flat:
            ax.axis("off")
        cache: Dict[str, pd.DataFrame] = {}
        for ax, (_, event) in zip(axes_array.flat, chosen.iterrows()):
            symbol = str(event.get("symbol"))
            if symbol not in cache:
                cache[symbol] = _load_symbol_ohlcv(db_path, symbol)
            window, offset = _window_for_event(cache[symbol], event)
            ax.axis("on")
            _draw_event(ax, window, event.to_dict(), offset)
            sample_rows.append(
                {
                    "tier": tier,
                    "event_id": event.get("event_id"),
                    "symbol": symbol,
                    "breakout_date": event.get("breakout_date"),
                    "score": event.get("publication_quality_score"),
                    "mfe_pct": event.get("mfe_pct"),
                    "mae_pct": event.get("mae_pct"),
                    "target_hit": bool(event.get("target_hit")),
                    "failure_5pct": bool(event.get("failure_5pct")),
                    "reasons": event.get("publication_quality_reasons"),
                }
            )
        fig.suptitle(f"{pattern_title} random visual audit: {tier}", fontsize=13)
        fig.tight_layout(rect=[0, 0, 1, 0.98])
        sheet_path = visual_dir / f"{tier}_random_contact_sheet.png"
        fig.savefig(sheet_path)
        plt.close(fig)
        sheets[tier] = str(sheet_path)
    pd.DataFrame(sample_rows).to_csv(visual_dir / "random_samples_by_tier.csv", index=False)
    return {"seed": seed, "sample_per_tier": sample_per_tier, "contact_sheets": sheets, "sample_csv": str(visual_dir / "random_samples_by_tier.csv")}


def _manual_visual_scoring_pack(events: pd.DataFrame, *, db_path: Path, out_dir: Path, sample_total: int, seed: int, pattern_title: str) -> Dict[str, Any]:
    rng = np.random.default_rng(seed + 101)
    scoring_dir = out_dir / "manual_visual_scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)
    scoring_csv = scoring_dir / "manual_visual_scoring_template.csv"
    existing_scores: Dict[str, Mapping[str, Any]] = {}
    existing_order: Dict[str, int] = {}
    if scoring_csv.exists():
        existing = pd.read_csv(scoring_csv).fillna("")
        for fallback_order, (_, row) in enumerate(existing.iterrows(), start=1):
            event_id = str(row.get("event_id"))
            existing_scores[event_id] = row.to_dict()
            try:
                existing_order[event_id] = int(row.get("sample_no"))
            except (TypeError, ValueError):
                existing_order[event_id] = fallback_order
    if existing_order:
        chosen = events[events["event_id"].astype(str).isin(existing_order)].copy()
        chosen["_manual_order"] = chosen["event_id"].astype(str).map(existing_order)
        chosen = chosen.sort_values("_manual_order").drop(columns=["_manual_order"]).head(sample_total).reset_index(drop=True)
    else:
        per_tier = max(1, int(math.ceil(sample_total / len(TIER_ORDER))))
        chosen_parts: List[pd.DataFrame] = []
        for tier in TIER_ORDER:
            subset = events[events["publication_quality_tier"].astype(str) == tier].copy()
            if subset.empty:
                continue
            size = min(per_tier, len(subset))
            chosen_parts.append(subset.loc[rng.choice(subset.index.to_numpy(), size=size, replace=False)].copy())
        chosen = pd.concat(chosen_parts, ignore_index=True).head(sample_total) if chosen_parts else events.iloc[:0].copy()
        chosen = chosen.sort_values(["publication_quality_tier", "symbol", "breakout_date"]).reset_index(drop=True)
    if chosen.empty:
        return {"sample_total": 0, "scoring_csv": None, "contact_sheet": None}

    cols = 2
    rows = int(math.ceil(len(chosen) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, max(4, rows * 3.0)), dpi=150)
    axes_array = np.atleast_1d(axes).reshape(rows, cols)
    for ax in axes_array.flat:
        ax.axis("off")
    cache: Dict[str, pd.DataFrame] = {}
    scoring_rows: List[Dict[str, Any]] = []
    for sample_no, (ax, (_, event)) in enumerate(zip(axes_array.flat, chosen.iterrows()), start=1):
        symbol = str(event.get("symbol"))
        if symbol not in cache:
            cache[symbol] = _load_symbol_ohlcv(db_path, symbol)
        window, offset = _window_for_event(cache[symbol], event)
        ax.axis("on")
        _draw_event(ax, window, event.to_dict(), offset)
        ax.text(0.01, 0.98, f"#{sample_no}", transform=ax.transAxes, va="top", ha="left", fontsize=10, weight="bold", color="#7A5195")
        previous = existing_scores.get(str(event.get("event_id")), {})
        scoring_rows.append(
            {
                "sample_no": sample_no,
                "event_id": event.get("event_id"),
                "symbol": symbol,
                "breakout_date": event.get("breakout_date"),
                "publication_quality_tier": event.get("publication_quality_tier"),
                "publication_quality_score": event.get("publication_quality_score"),
                "path_quality_bucket": event.get("path_quality_bucket"),
                "tradability_quality_bucket": event.get("tradability_quality_bucket"),
                "mfe_pct": event.get("mfe_pct"),
                "mae_pct": event.get("mae_pct"),
                "manual_visual_score_1_to_5": previous.get("manual_visual_score_1_to_5", ""),
                "manual_visual_bucket": previous.get("manual_visual_bucket", ""),
                "manual_reviewer_note": previous.get("manual_reviewer_note", ""),
            }
        )
    fig.suptitle(f"{pattern_title} manual visual scoring pack", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    sheet_path = scoring_dir / "manual_visual_scoring_contact_sheet.png"
    fig.savefig(sheet_path)
    plt.close(fig)
    pd.DataFrame(scoring_rows).to_csv(scoring_csv, index=False)
    return {"sample_total": int(len(scoring_rows)), "scoring_csv": str(scoring_csv), "contact_sheet": str(sheet_path)}


def _manual_visual_score_comparison(scoring_csv: Optional[str]) -> Dict[str, Any]:
    if not scoring_csv:
        return {"status": "NOT_READY", "reason": "missing_scoring_csv"}
    path = Path(scoring_csv)
    if not path.exists():
        return {"status": "NOT_READY", "reason": "scoring_csv_not_found"}
    frame = pd.read_csv(path)
    scores = pd.to_numeric(frame.get("manual_visual_score_1_to_5"), errors="coerce")
    scored = frame[scores.notna()].copy()
    if scored.empty:
        return {"status": "PENDING_MANUAL_REVIEW", "scored_n": 0, "scoring_csv": str(path)}
    scored["manual_visual_score_1_to_5"] = pd.to_numeric(scored["manual_visual_score_1_to_5"], errors="coerce")
    rows = []
    for tier, group in scored.groupby("publication_quality_tier", dropna=False):
        rows.append({"publication_quality_tier": str(tier), "n": int(len(group)), "manual_score_median": round(float(group["manual_visual_score_1_to_5"].median()), 2), "manual_score_mean": round(float(group["manual_visual_score_1_to_5"].mean()), 2)})
    scored_tiers = {str(row.get("publication_quality_tier")) for row in rows}
    missing_scored_tiers = [tier for tier in TIER_ORDER if tier not in scored_tiers]
    return {
        "status": "SCORED",
        "scored_n": int(len(scored)),
        "by_tier": rows,
        "missing_scored_tiers": missing_scored_tiers,
        "current_premium_review_status": "NEEDS_REVIEW" if "premium" in missing_scored_tiers else "SCORED",
        "scoring_csv": str(path),
    }


def _premium_visual_validation_pack(events: pd.DataFrame, *, db_path: Path, out_dir: Path, sample_total: int, seed: int, pattern_title: str) -> Dict[str, Any]:
    scoring_dir = out_dir / "manual_visual_scoring"
    scoring_dir.mkdir(parents=True, exist_ok=True)
    scoring_csv = scoring_dir / "premium_visual_validation_template.csv"
    sheet_path = scoring_dir / "premium_visual_validation_contact_sheet.png"

    existing_scores: Dict[str, Mapping[str, Any]] = {}
    existing_order: Dict[str, int] = {}
    if scoring_csv.exists():
        existing = pd.read_csv(scoring_csv).fillna("")
        for fallback_order, (_, row) in enumerate(existing.iterrows(), start=1):
            event_id = str(row.get("event_id"))
            existing_scores[event_id] = row.to_dict()
            try:
                existing_order[event_id] = int(row.get("sample_no"))
            except (TypeError, ValueError):
                existing_order[event_id] = fallback_order

    premium = events[events["publication_quality_tier"].astype(str) == "premium"].copy()
    if premium.empty:
        return {"sample_total": 0, "scoring_csv": str(scoring_csv), "contact_sheet": str(sheet_path), "status": "NO_PREMIUM_EVENTS"}

    rng = np.random.default_rng(seed + 303)
    if existing_order:
        chosen = premium[premium["event_id"].astype(str).isin(existing_order)].copy()
        chosen["_manual_order"] = chosen["event_id"].astype(str).map(existing_order)
        chosen = chosen.sort_values("_manual_order").drop(columns=["_manual_order"]).head(sample_total).reset_index(drop=True)
        if len(chosen) < int(sample_total):
            chosen_ids = set(chosen["event_id"].astype(str))
            remaining = premium[~premium["event_id"].astype(str).isin(chosen_ids)].copy()
            if not remaining.empty:
                size = min(int(sample_total) - len(chosen), len(remaining))
                extra = remaining.loc[rng.choice(remaining.index.to_numpy(), size=size, replace=False)].copy()
                extra = extra.sort_values(["symbol", "breakout_date"]).reset_index(drop=True)
                chosen = pd.concat([chosen, extra], ignore_index=True).head(sample_total)
    else:
        size = min(int(sample_total), len(premium))
        chosen = premium.loc[rng.choice(premium.index.to_numpy(), size=size, replace=False)].copy()
        chosen = chosen.sort_values(["symbol", "breakout_date"]).reset_index(drop=True)

    if chosen.empty:
        return {"sample_total": 0, "scoring_csv": str(scoring_csv), "contact_sheet": str(sheet_path), "status": "NO_CURRENT_SCORED_PREMIUM"}

    cols = 2
    rows = int(math.ceil(len(chosen) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, max(4, rows * 3.0)), dpi=150)
    axes_array = np.atleast_1d(axes).reshape(rows, cols)
    for ax in axes_array.flat:
        ax.axis("off")
    cache: Dict[str, pd.DataFrame] = {}
    scoring_rows: List[Dict[str, Any]] = []
    for sample_no, (ax, (_, event)) in enumerate(zip(axes_array.flat, chosen.iterrows()), start=1):
        symbol = str(event.get("symbol"))
        if symbol not in cache:
            cache[symbol] = _load_symbol_ohlcv(db_path, symbol)
        window, offset = _window_for_event(cache[symbol], event)
        ax.axis("on")
        _draw_event(ax, window, event.to_dict(), offset)
        ax.text(0.01, 0.98, f"P#{sample_no}", transform=ax.transAxes, va="top", ha="left", fontsize=10, weight="bold", color="#7A5195")
        previous = existing_scores.get(str(event.get("event_id")), {})
        scoring_rows.append(
            {
                "sample_no": sample_no,
                "event_id": event.get("event_id"),
                "symbol": symbol,
                "breakout_date": event.get("breakout_date"),
                "publication_quality_tier": event.get("publication_quality_tier"),
                "publication_quality_score": event.get("publication_quality_score"),
                "path_quality_bucket": event.get("path_quality_bucket"),
                "tradability_quality_bucket": event.get("tradability_quality_bucket"),
                "mfe_pct": event.get("mfe_pct"),
                "mae_pct": event.get("mae_pct"),
                "target_first_before_adverse_5pct": event.get("target_first_before_adverse_5pct"),
                "manual_visual_score_1_to_5": previous.get("manual_visual_score_1_to_5", ""),
                "manual_visual_bucket": previous.get("manual_visual_bucket", ""),
                "manual_reviewer_note": previous.get("manual_reviewer_note", ""),
            }
        )
    fig.suptitle(f"{pattern_title} premium visual validation pack", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(sheet_path)
    plt.close(fig)
    pd.DataFrame(scoring_rows).to_csv(scoring_csv, index=False)
    return {"sample_total": int(len(scoring_rows)), "scoring_csv": str(scoring_csv), "contact_sheet": str(sheet_path), "status": "READY"}


def _premium_visual_validation_summary(scoring_csv: Optional[str]) -> Dict[str, Any]:
    if not scoring_csv:
        return {"status": "NOT_READY", "reason": "missing_scoring_csv"}
    path = Path(scoring_csv)
    if not path.exists():
        return {"status": "NOT_READY", "reason": "scoring_csv_not_found"}
    frame = pd.read_csv(path)
    scores = pd.to_numeric(frame.get("manual_visual_score_1_to_5"), errors="coerce")
    scored = frame[scores.notna()].copy()
    if scored.empty:
        return {"status": "PENDING_MANUAL_REVIEW", "scored_n": 0, "scoring_csv": str(path)}
    scored["manual_visual_score_1_to_5"] = pd.to_numeric(scored["manual_visual_score_1_to_5"], errors="coerce")
    median = round(float(scored["manual_visual_score_1_to_5"].median()), 2)
    mean = round(float(scored["manual_visual_score_1_to_5"].mean()), 2)
    pass_rate = round(float((scored["manual_visual_score_1_to_5"] >= 4).mean() * 100.0), 2)
    return {
        "status": "SCORED",
        "scored_n": int(len(scored)),
        "manual_score_median": median,
        "manual_score_mean": mean,
        "manual_pass_rate_pct": pass_rate,
        "premium_visual_gate": "PASS" if median >= 4.0 and pass_rate >= 70.0 else "REVIEW",
        "scoring_csv": str(path),
    }


def _lookup(rows: Sequence[Mapping[str, Any]], **criteria: Any) -> Optional[Mapping[str, Any]]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    return None


def _render_markdown(summary: Mapping[str, Any]) -> str:
    pattern_title = str(summary.get("pattern_title") or "Triangle")
    target_rows = list(summary.get("target_family_by_publication_tier") or [])
    threshold_rows = list(summary.get("tier_threshold_sensitivity") or [])
    overlap_rows = list(summary.get("overlap_cooldown_sensitivity") or [])
    precision_rows = list(summary.get("precision_bootstrap_summary") or [])
    temporal_rows = list(summary.get("temporal_split_robustness") or [])
    interaction_rows = list(summary.get("regime_liquidity_interaction") or [])
    manual_comparison = summary.get("manual_visual_score_comparison") if isinstance(summary.get("manual_visual_score_comparison"), Mapping) else {}
    premium_validation = summary.get("premium_visual_validation_summary") if isinstance(summary.get("premium_visual_validation_summary"), Mapping) else {}
    ps_base = _lookup(target_rows, tier="premium+standard", target_multiple=0.5) or {}
    all_base = _lookup(target_rows, tier="all", target_multiple=0.5) or {}
    data_base = _lookup(target_rows, tier="data_limited", target_multiple=0.5) or {}
    premium_strict = _lookup(threshold_rows, variant="strict", tier="premium") or {}
    ps_cooldown_90 = _lookup(overlap_rows, scope="premium+standard", variant="cooldown_90d") or {}
    ps_one_symbol = _lookup(overlap_rows, scope="premium+standard", variant="one_event_per_symbol") or {}
    ps_precision = _lookup(precision_rows, scope="premium+standard") or {}
    hit_ci = ps_precision.get("target_hit_wilson") if isinstance(ps_precision.get("target_hit_wilson"), Mapping) else {}
    first_ci = ps_precision.get("target_first_wilson") if isinstance(ps_precision.get("target_first_wilson"), Mapping) else {}
    ratio_ci = ps_precision.get("mfe_mae_ratio_bootstrap_ci") if isinstance(ps_precision.get("mfe_mae_ratio_bootstrap_ci"), Mapping) else {}
    cluster_hit_ci = ps_precision.get("target_hit_cluster_ci") if isinstance(ps_precision.get("target_hit_cluster_ci"), Mapping) else {}
    cluster_first_ci = ps_precision.get("target_first_cluster_ci") if isinstance(ps_precision.get("target_first_cluster_ci"), Mapping) else {}
    late_third = _lookup(temporal_rows, split_type="sample_thirds", period="late_third") or {}
    weak_interactions = [
        row
        for row in interaction_rows
        if int(row.get("n") or 0) >= 30 and float(row.get("target_first_before_adverse_5pct_rate_pct") or 0) < 45.0
    ]

    lines = [
        f"# {pattern_title} Publication Quality Audit",
        "",
        "## Kết luận nhanh",
        "",
        (
            "- `premium+standard` giữ vai trò nhóm public-grade: "
            f"N={ps_base.get('n')}, hit 0.5x={ps_base.get('target_hit_rate_pct')}%, "
            f"target-first={ps_base.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"failure={ps_base.get('failure_5pct_rate_pct')}%, "
            f"MFE/MAE={ps_base.get('mfe_mae_median_ratio')}."
        ),
        (
            "- Precision đủ tốt cho headline: "
            f"Wilson hit 0.5x [{hit_ci.get('low')}, {hit_ci.get('high')}], "
            f"Wilson target-first [{first_ci.get('low')}, {first_ci.get('high')}], "
            f"cluster bootstrap MFE/MAE [{ratio_ci.get('low')}, {ratio_ci.get('high')}]."
        ),
        (
            "- Cluster bootstrap theo mã: "
            f"hit 0.5x [{cluster_hit_ci.get('low')}, {cluster_hit_ci.get('high')}], "
            f"target-first [{cluster_first_ci.get('low')}, {cluster_first_ci.get('high')}]."
        ),
        (
            "- Temporal split: "
            f"late third N={late_third.get('n')}, target-first={late_third.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"MFE/MAE={late_third.get('mfe_mae_median_ratio')}."
        ),
        (
            "- Regime x liquidity interaction: "
            f"{len(weak_interactions)} bucket >=30 mẫu có target-first dưới 45%."
        ),
        (
            "- Manual visual scoring: "
            f"status={manual_comparison.get('status')}, scored_n={manual_comparison.get('scored_n')}, "
            f"premium_review={manual_comparison.get('current_premium_review_status')}."
        ),
        (
            "- Premium visual validation: "
            f"status={premium_validation.get('status')}, scored_n={premium_validation.get('scored_n')}, "
            f"median={premium_validation.get('manual_score_median')}, "
            f"pass_rate={premium_validation.get('manual_pass_rate_pct')}%, "
            f"gate={premium_validation.get('premium_visual_gate')}."
        ),
        (
            "- Toàn mẫu thấp hơn ở path quality: "
            f"target-first={all_base.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"MFE/MAE={all_base.get('mfe_mae_median_ratio')}."
        ),
        (
            "- `data_limited` đúng là nhóm phải hạ trọng số: "
            f"target-first={data_base.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"failure={data_base.get('failure_5pct_rate_pct')}%, "
            f"MFE/MAE={data_base.get('mfe_mae_median_ratio')}."
        ),
        (
            "- Strict premium vẫn đứng vững: "
            f"N={premium_strict.get('n')}, target-first={premium_strict.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"failure={premium_strict.get('failure_5pct_rate_pct')}%, "
            f"MFE/MAE={premium_strict.get('mfe_mae_median_ratio')}."
        ),
        (
            "- Cooldown không làm sụp kết quả: `premium+standard` cooldown 90 ngày giữ "
            f"{ps_cooldown_90.get('retention_pct')}% mẫu và target-first={ps_cooldown_90.get('target_first_before_adverse_5pct_rate_pct')}%."
        ),
        (
            "- One-event-per-symbol là stress test mạnh: còn "
            f"N={ps_one_symbol.get('n')}, target-first={ps_one_symbol.get('target_first_before_adverse_5pct_rate_pct')}%, "
            f"MFE/MAE={ps_one_symbol.get('mfe_mae_median_ratio')}."
        ),
        "",
        "## Quyết định",
        "",
        (
            "Lớp `publication_quality_tier` nên được giữ. Nó không chỉ làm đẹp bảng thống kê, "
            "mà tách được nhóm đường giá kém sạch khỏi nhóm đủ điều kiện diễn giải công khai. "
            "Manual scoring được dùng như cổng kiểm tra bằng mắt; nếu premium không đạt median tối thiểu 4, "
            "tier cần được hiệu chỉnh trước khi đưa vào chapter."
        ),
        "",
        "## Artifacts",
        "",
    ]
    visual = summary.get("visual_audit") or {}
    sheets = visual.get("contact_sheets") or {}
    for tier in TIER_ORDER:
        if tier in sheets:
            lines.append(f"- `{tier}`: `{sheets[tier]}`")
    lines.extend(
        [
            f"- target table: `target_family_by_publication_tier.csv`",
            f"- threshold sensitivity: `tier_threshold_sensitivity.csv`",
            f"- overlap sensitivity: `overlap_cooldown_sensitivity.csv`",
            f"- precision: `precision_bootstrap_summary.csv`",
            f"- subgroup robustness: `public_grade_subgroup_robustness.csv`",
            f"- temporal split: `temporal_split_robustness.csv`",
            f"- regime-liquidity interaction: `regime_liquidity_interaction.csv`",
            f"- manual visual scoring: `manual_visual_scoring/manual_visual_scoring_template.csv`",
            f"- premium visual validation: `manual_visual_scoring/premium_visual_validation_template.csv`",
        ]
    )
    if manual_comparison.get("status") == "SCORED":
        lines.extend(["", "## Manual visual scoring summary", ""])
        for row in manual_comparison.get("by_tier") or []:
            lines.append(
                f"- `{row.get('publication_quality_tier')}`: n={row.get('n')}, "
                f"median={row.get('manual_score_median')}, mean={row.get('manual_score_mean')}"
            )
    if premium_validation.get("status") == "SCORED":
        lines.extend(
            [
                "",
                "## Premium visual validation",
                "",
                (
                    f"- n={premium_validation.get('scored_n')}, "
                    f"median={premium_validation.get('manual_score_median')}, "
                    f"mean={premium_validation.get('manual_score_mean')}, "
                    f"pass_rate={premium_validation.get('manual_pass_rate_pct')}%, "
                    f"gate={premium_validation.get('premium_visual_gate')}"
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    events_csv: Path,
    path_csv: Path,
    db_path: Path,
    out_dir: Path,
    sample_per_tier: int,
    manual_sample_total: int,
    premium_manual_sample_total: int,
    seed: int,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events = _load_events(events_csv)
    path = _load_path(path_csv)
    pattern_id = _infer_pattern_id(events)
    pattern_meta = _pattern_meta(pattern_id)
    pattern_title = pattern_meta["title"]

    target_rows = _tier_target_table(events, path)
    threshold_rows = _tier_threshold_sensitivity(events, path)
    overlap_rows = _overlap_sensitivity(events, path)
    precision_rows = _precision_rows(events, path, seed=seed)
    subgroup_rows = _subgroup_robustness(events, path)
    temporal_rows = _temporal_split_rows(events, path)
    interaction_rows = _regime_liquidity_interaction(events, path)
    visual = _visual_audit(events, db_path=db_path, out_dir=out_dir, sample_per_tier=sample_per_tier, seed=seed, pattern_title=pattern_title)
    manual_pack = _manual_visual_scoring_pack(events, db_path=db_path, out_dir=out_dir, sample_total=manual_sample_total, seed=seed, pattern_title=pattern_title)
    manual_comparison = _manual_visual_score_comparison(manual_pack.get("scoring_csv"))
    premium_validation_pack = _premium_visual_validation_pack(events, db_path=db_path, out_dir=out_dir, sample_total=premium_manual_sample_total, seed=seed, pattern_title=pattern_title)
    premium_validation_summary = _premium_visual_validation_summary(premium_validation_pack.get("scoring_csv"))

    pd.DataFrame(target_rows).to_csv(out_dir / "target_family_by_publication_tier.csv", index=False)
    pd.DataFrame(threshold_rows).to_csv(out_dir / "tier_threshold_sensitivity.csv", index=False)
    pd.DataFrame(overlap_rows).to_csv(out_dir / "overlap_cooldown_sensitivity.csv", index=False)
    pd.DataFrame(precision_rows).to_csv(out_dir / "precision_bootstrap_summary.csv", index=False)
    pd.DataFrame(subgroup_rows).to_csv(out_dir / "public_grade_subgroup_robustness.csv", index=False)
    pd.DataFrame(temporal_rows).to_csv(out_dir / "temporal_split_robustness.csv", index=False)
    pd.DataFrame(interaction_rows).to_csv(out_dir / "regime_liquidity_interaction.csv", index=False)

    summary = {
        "audit_id": pattern_meta["audit_id"],
        "pattern_id": pattern_id,
        "pattern_title": pattern_title,
        "pattern_vietnamese_title": pattern_meta["vietnamese_title"],
        "events_csv": str(events_csv),
        "path_csv": str(path_csv),
        "db_path": str(db_path),
        "event_count": int(len(events)),
        "tier_counts": events["publication_quality_tier"].fillna("unknown").value_counts().to_dict(),
        "target_family_by_publication_tier": target_rows,
        "tier_threshold_sensitivity": threshold_rows,
        "overlap_cooldown_sensitivity": overlap_rows,
        "precision_bootstrap_summary": precision_rows,
        "public_grade_subgroup_robustness": subgroup_rows,
        "temporal_split_robustness": temporal_rows,
        "regime_liquidity_interaction": interaction_rows,
        "visual_audit": visual,
        "manual_visual_scoring": manual_pack,
        "manual_visual_score_comparison": manual_comparison,
        "premium_visual_validation": premium_validation_pack,
        "premium_visual_validation_summary": premium_validation_summary,
        "interpretation": {
            "tier_sensitivity": "PASS if premium+standard keeps stronger target-first and MFE/MAE than data_limited under lenient/base/strict cuts.",
            "overlap_sensitivity": "PASS if 0.5x target-first and MFE/MAE do not collapse under 40d/60d/90d cooldown.",
            "cluster_bootstrap": "Resamples whole symbols so repeated events from the same ticker do not behave like independent draws.",
            "temporal_split": "Checks whether public-grade results survive across calendar periods and equal sample thirds.",
            "regime_liquidity_interaction": "Checks whether the signal is concentrated in one market-state/liquidity bucket.",
            "visual_audit": "Manual review required; charts are sampled by tier with a fixed seed.",
        },
    }
    _write_json(out_dir / "triangle_publication_quality_audit.json", summary)
    (out_dir / "triangle_publication_quality_audit.md").write_text(_render_markdown(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Triangle Family publication-quality tiers.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--sample-per-tier", type=int, default=10)
    parser.add_argument("--manual-sample-total", type=int, default=20)
    parser.add_argument("--premium-manual-sample-total", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260519)
    args = parser.parse_args()

    summary = run_audit(
        events_csv=Path(args.events),
        path_csv=Path(args.path),
        db_path=Path(args.db),
        out_dir=Path(args.out_dir),
        sample_per_tier=int(args.sample_per_tier),
        manual_sample_total=int(args.manual_sample_total),
        premium_manual_sample_total=int(args.premium_manual_sample_total),
        seed=int(args.seed),
    )
    print(json.dumps({"out_dir": str(Path(args.out_dir)), "event_count": summary["event_count"], "tier_counts": summary["tier_counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
