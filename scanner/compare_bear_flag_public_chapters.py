"""Compare stock-series and DB-active Bear Flag public chapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_OLD = Path("artifacts/scanner_v2/bear_flags_public_chapter")
DEFAULT_NEW = Path("artifacts/scanner_v2/bear_flags_public_chapter_db_active")
DEFAULT_OUT = Path("artifacts/scanner_v2/bear_flags_public_chapter_db_active_comparison")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pdf_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pages": 0, "chars": 0, "size_bytes": 0, "missing": True}
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"pages": len(reader.pages), "chars": len(text), "size_bytes": path.stat().st_size, "missing": False}


def _headline(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    return stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}


def _summary(label: str, chapter_dir: Path) -> dict[str, Any]:
    payload = _read_json(chapter_dir / "bear_flag_public_chapter_payload.json")
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    headline = _headline(payload)
    examples = payload.get("example_events") if isinstance(payload.get("example_events"), Mapping) else {}
    return {
        "chapter_id": label,
        "pdf": _pdf_info(chapter_dir / "bear_flag_public_chapter.pdf"),
        "detection_count": stats.get("detection_count"),
        "symbols_scanned": stats.get("symbols_scanned"),
        "headline_scope": headline.get("aggregate_id") or headline.get("branch_id"),
        "headline_n": headline.get("n"),
        "headline_hit_rate": headline.get("base_target_hit_rate"),
        "headline_target_first_rate": headline.get("base_target_first_before_adverse_5pct_rate"),
        "headline_failure_5pct_rate": headline.get("failure_5pct_rate"),
        "headline_mfe_mae_ratio": headline.get("mfe_mae_median_ratio"),
        "example_symbols": {key: event.get("symbol") for key, event in examples.items() if isinstance(event, Mapping)},
    }


def build_comparison(*, old_dir: Path = DEFAULT_OLD, new_dir: Path = DEFAULT_NEW, out_dir: Path = DEFAULT_OUT) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    old = _summary("stock_series_active", old_dir)
    new = _summary("db_active", new_dir)
    delta = {
        "headline_n_delta": int(new.get("headline_n") or 0) - int(old.get("headline_n") or 0),
        "headline_hit_delta_pp": round(float(new.get("headline_hit_rate") or 0) - float(old.get("headline_hit_rate") or 0), 2),
        "headline_target_first_delta_pp": round(float(new.get("headline_target_first_rate") or 0) - float(old.get("headline_target_first_rate") or 0), 2),
        "headline_failure_delta_pp": round(float(new.get("headline_failure_5pct_rate") or 0) - float(old.get("headline_failure_5pct_rate") or 0), 2),
        "headline_mfe_mae_delta": round(float(new.get("headline_mfe_mae_ratio") or 0) - float(old.get("headline_mfe_mae_ratio") or 0), 2),
    }
    promote = (
        int(new.get("headline_n") or 0) > int(old.get("headline_n") or 0)
        and float(new.get("headline_hit_rate") or 0) >= 65.0
        and float(new.get("headline_failure_5pct_rate") or 100.0) <= 20.0
        and float(new.get("headline_mfe_mae_ratio") or 0) >= 1.2
    )
    payload = {
        "audit_version": "bear_flag_public_chapter_db_active_comparison_v1",
        "old": old,
        "new": new,
        "delta": delta,
        "decision": "PROMOTE_DB_ACTIVE_CHAPTER_CANDIDATE" if promote else "KEEP_STOCK_SERIES_PUBLIC_CHAPTER",
        "note": "Promotion means DB-active becomes the preferred Bear Flag chapter candidate after source-parity review.",
    }
    json_path = out_dir / "bear_flag_public_chapter_comparison.json"
    md_path = out_dir / "bear_flag_public_chapter_comparison.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Bear Flag public chapter comparison",
        "",
        f"**Decision:** {payload['decision']}",
        "",
        "| Version | PDF pages | PDF chars | All N | Headline N | Hit | Target-first | Failure | MFE/MAE | Examples |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in (old, new):
        lines.append(
            f"| {row['chapter_id']} | {row['pdf']['pages']} | {row['pdf']['chars']} | {row.get('detection_count')} | {row.get('headline_n')} | {row.get('headline_hit_rate')}% | {row.get('headline_target_first_rate')}% | {row.get('headline_failure_5pct_rate')}% | {row.get('headline_mfe_mae_ratio')} | {row.get('example_symbols')} |"
        )
    lines.extend(
        [
            "",
            "## Delta",
            "",
            f"- Headline N: {delta['headline_n_delta']}",
            f"- Hit: {delta['headline_hit_delta_pp']} pp",
            f"- Target-first: {delta['headline_target_first_delta_pp']} pp",
            f"- Failure: {delta['headline_failure_delta_pp']} pp",
            f"- MFE/MAE: {delta['headline_mfe_mae_delta']}",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Bear Flag public chapter variants.")
    parser.add_argument("--old-dir", default=str(DEFAULT_OLD))
    parser.add_argument("--new-dir", default=str(DEFAULT_NEW))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    paths = build_comparison(old_dir=Path(args.old_dir), new_dir=Path(args.new_dir), out_dir=Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
