# Scanner Scripts

## Legacy quarantine

`pattern_scanner.py` and `run_full_scan.py` are legacy entrypoints. They are
blocked by default during the Scanner V2 rebuild.

Historical comparison only:

```bash
CHARTPATTERNSCAN_ALLOW_LEGACY_SCANNER=1 python3 scanner/run_full_scan.py ...
```

New official research/PDF work should start from `scanner/v2/`.

Thư mục `scanner/` được chia thành các nhóm script entrypoint như sau:

## `build_*`

Sinh artifact, báo cáo, book, snapshot hoặc review pack.

Ví dụ:
- `build_book_v2.py`
- `build_pattern_monographs.py`
- `build_vietnam_research_report.py`
- `build_phase3_governance.py`

## `report_*`

Sinh report đọc trực tiếp từ scan results DB.

Ví dụ:
- `report_bulkowski.py`
- `report_symbol.py`

## `audit_*`

Chạy audit/compliance/quality evaluation.

Ví dụ:
- `audit_kpi.py`
- `audit_book_v2_readiness.py`
- `audit_spec.py`
- `validate_book_v2_readiness_gate.py`

## `review_*`

Các script review hoặc quality gate.

Ví dụ:
- `review_pattern_sets.py`
- `review_plot_helpers.py`

## Legacy wrappers

Một số tên cũ vẫn được giữ lại chỉ để tương thích ngược:
- `bulkowski_report.py`
- `symbol_report.py`
- `spec_audit.py`
- `phase3_governance.py`

Các wrapper này chỉ chuyển tiếp sang tên chuẩn mới.
