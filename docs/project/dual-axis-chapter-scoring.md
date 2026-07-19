# Dual-Axis Chapter Scoring

Từ thời điểm áp dụng rule này, mọi chapter phải được đọc trên hai trục độc lập.

## Hai trục điểm

| Trục | Câu hỏi | Nhãn được phép |
|---|---|---|
| Publication / reference | Chapter có đủ tốt để đọc như tài liệu Bulkowski Việt Nam không? | `publication-final`, `investment-reference-candidate`, `defensive/informational-reference` |
| Tradable / execution | Pattern có qua entry/exit, phí, trượt giá, sizing, portfolio, OOS, walk-forward không? | `not_tested`, `tradable_research_candidate_blocked`, `tradable_final_95` |

`publication-final` không bao giờ tự động đồng nghĩa với `tradable-final-95`.

## Tradable preflight

Từ sau vòng governance này, mọi chapter final còn có thêm một lớp `tradable-preflight`. Đây là lớp rà soát nhanh bằng dữ liệu event-level đã có: độ dày mẫu, MFE/MAE, target-first, failure, chất lượng path và thanh khoản.

`tradable-preflight` chỉ trả lời câu hỏi: chapter nào đáng ưu tiên viết scorecard thực thi đầy đủ. Nó không được dùng thay cho `tradable-final-95`, vì chưa có entry/exit/cost/sizing/portfolio/OOS/walk-forward.

Từ vòng chuẩn hóa sau này, preflight phải dùng **target đã hiệu chuẩn của chapter** nếu target calibration đã được khóa. Nếu chapter có nhánh publication/source-safe rõ ràng và aggregate làm mờ tín hiệu, preflight được phép dùng nhánh đó, nhưng phải ghi `preflight_branch_id`, `aggregate_preflight_score` và warning `branch_scoped_preflight`. Nhánh preflight chỉ được chọn bằng biến hình thái, thanh khoản, regime, confirmation hoặc quality đã có trước outcome; không được dùng MFE/MAE/target-hit để định nghĩa nhánh.

## Điều kiện gọi `tradable-final-95`

Một chapter chỉ được gọi là `tradable-final-95` khi có đủ:

- executable rule: entry, exit, stop/target, holding horizon;
- cost model: commission, tax, slippage;
- sizing and portfolio constraints;
- validation/holdout split;
- fixed-rule walk-forward;
- cost stress and Monte Carlo diagnostics;
- scorecard >= 95;
- release candidate PASS;
- không còn promotion blocker.

Nếu thiếu lớp thực thi, chapter phải ghi `tradable_status = not_tested`.

Sau vòng full-layer ngày 2026-05-21, mọi chapter final hiện đã có ít nhất một lớp thực thi:

- `bull_flags`: scorecard chuyên biệt và đạt `tradable-final-95`.
- `bull_pennants`: scorecard chuyên biệt, đạt research candidate nhưng còn blocker walk-forward.
- 5 ứng viên mạnh nhất ngoài Bull Flag có thêm `priority_candidate_layer`: Bull Pennant, Symmetrical Triangle, Ascending Triangle, Falling Wedge, Double Bottom Adam & Adam.
- các chapter còn lại: scorecard generic direction-aware và branch-optimization layer, đã test entry/exit/cost/sizing/OOS/walk-forward nhưng đang `tradable_tested_blocked`.
- Khi một chapter đã gần 95 nhưng còn blocker, cần chạy thêm ceiling audit trước khi tiếp tục tối ưu. Bull Pennant hiện có `bull_pennant_tradable_ceiling_audit_v1`, kết luận trần chẩn đoán hiện tại là 93.80 và blocker còn lại vẫn là `walk_forward_has_negative_fold`.

`tradable_tested_blocked` nghĩa là đã chạy lớp thực thi nhưng chưa đủ điều kiện nâng lên tradable final; nó khác với `not_tested`.

Governance được phép chọn bằng chứng tốt nhất giữa `generic_tradable_layer`, `branch_optimization_layer` và `priority_candidate_layer`, nhưng không được lấy score thấp hơn để thay thế score tốt hơn đã có. Điều này ngăn việc tối ưu quá hẹp làm giảm chất lượng tổng thể.

Với preflight, governance đọc trực tiếp `chapter_tradable_preflight_matrix.*`. Nếu preflight tăng do target calibration hoặc branch scope thì đó là cải thiện ở tầng triage/publication framing, không tự động nâng `tradable_status`.

Khi một mẫu còn yếu ở preflight nhưng có thể có branch tốt hơn, phải chạy `preflight_branch_ceiling_audit_v1` trước khi tiếp tục tối ưu. Audit này so branch đang chọn với các branch còn lại trong ma trận preflight; nếu không còn branch nào nâng thêm tối thiểu 3 điểm, blocker phải được chuyển sang dữ liệu/scope/thực thi thay vì tiếp tục siết nhánh.

## No-overlift guard

Khi một chapter đã gần `tradable-final-95`, không được cố nâng điểm bằng cách đổi chuẩn sau khi thấy kết quả. Guard hiện hành là `tradable_no_overlift_guard_v1`.

Một chapter phải dừng tối ưu, không promote, nếu có bất kỳ điều kiện nào sau:

- best diagnostic score vẫn dưới 95;
- best diagnostic branch vẫn còn promotion blocker;
- fixed-rule walk-forward còn fold âm theo contract hiện tại;
- score 95 chỉ đạt được bằng cách nới hoặc đổi fold contract;
- score 95 chỉ đạt được bằng cách chọn trực tiếp trên holdout/walk-forward;
- sample bị siết quá hẹp so với release candidate mà không có rule pre-registered.

Bull Pennant hiện là ví dụ chuẩn cho rule này: ceiling audit tốt nhất đạt 93.80, vẫn còn `walk_forward_has_negative_fold`, nên quyết định đúng là `STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY`, không ép lên `tradable-final-95`.

Các ứng viên còn lại phải đi qua cùng guard bằng `other_candidate_tradable_ceiling_audit_v1`. Audit này không chạy branch mining mới; nó đọc bằng chứng đã có từ `generic_tradable_layer`, `branch_optimization_layer`, `priority_candidate_layer`, chọn evidence tốt nhất và chặn promotion nếu còn score/blocker/scope/walk-forward fail.

Khi giải quyết từng pattern, dùng thêm local blocker audit để cô lập nguyên nhân riêng của mẫu hình. Local audit được phép cải thiện `tradable_evidence_id` nếu score cao hơn các layer cũ, nhưng vẫn bị no-overlift guard chặn nếu còn blocker.

Sau các vòng tối ưu pattern-specific, phải chạy `tradable_candidate_ceiling_audit_v1` cho nhóm còn dưới 95 nhưng vẫn đáng nâng. Audit này kiểm tra toàn bộ bằng chứng đã tính (`generic_tradable_layer`, `branch_optimization_layer`, `priority_candidate_layer`, local blocker audits) và dừng nếu không còn evidence nào nâng thêm tối thiểu 3 điểm hoặc đủ điều kiện promotion review. Khi audit kết luận `STOP_TRADABLE_CEILING_REACHED`, hướng xử lý tiếp theo phải là dữ liệu mới, phạm vi công cụ mới, hoặc thiết kế execution mới đã preregister; không tiếp tục siết nhánh trên cùng artifact.

## Family-level rescue evidence

Một số family có nhiều biến thể hình thái nhưng từng biến thể riêng lẻ quá mỏng để qua validation/holdout. Khi đó được phép chạy audit cấp family, với điều kiện biến thể chỉ là subgroup/reporting dimension chứ không phải bằng chứng nâng hạng riêng từng biến thể.

Rule hiện hành là `double_family_tradable_rescue_v1`:

- Double Bottoms có thể dùng family-level evidence cho direct long cash review nếu score >= 95, không còn hard blocker, fixed walk-forward không có fold âm, và branch không dùng outcome để chọn mẫu.
- Double Tops chỉ được dùng như defensive/informational evidence trên cash equities, kể cả khi score thống kê cao, vì scope downside không phải direct long cash setup.
- Nếu family branch được promote review, các biến thể Adam/Eve vẫn phải in trade depth, return, win-rate và caveat riêng; không được ghi rằng từng biến thể mỏng đã tự đạt `tradable-final-95`.

## Artifact bắt buộc

Ma trận hiện hành nằm ở:

- `artifacts/final_chapters/governance/chapter_governance_matrix.json`
- `artifacts/final_chapters/governance/chapter_governance_matrix.csv`
- `artifacts/final_chapters/governance/chapter_governance_matrix.md`
- `artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json`
- `artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.csv`
- `artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.md`
- `artifacts/final_chapters/governance/preflight_branch_ceiling_audit.json`
- `artifacts/final_chapters/governance/preflight_branch_ceiling_audit.csv`
- `artifacts/final_chapters/governance/preflight_branch_ceiling_audit.md`
- `artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.json`
- `artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.csv`
- `artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.md`
- `artifacts/scanner_v2/double_family_tradable_rescue/double_family_tradable_rescue.json`
- `artifacts/scanner_v2/double_family_tradable_rescue/double_family_tradable_rescue.csv`
- `artifacts/scanner_v2/double_family_tradable_rescue/double_family_tradable_rescue.md`

Lệnh cập nhật:

```bash
python3 scanner/build_chapter_tradable_preflight_matrix.py
python3 scanner/run_chapter_tradable_layer.py --reuse-existing
python3 scanner/run_chapter_branch_optimization.py --reuse-existing
python3 scanner/run_priority_candidate_tradable_optimization.py --reuse-existing
python3 scanner/run_bull_pennant_tradable_ceiling_audit.py
python3 scanner/run_other_candidate_tradable_ceiling_audit.py
python3 scanner/analyze_ascending_triangle_tradable_blockers.py
python3 scanner/analyze_symmetrical_triangle_tradable_blockers.py
python3 scanner/analyze_falling_wedge_tradable_blockers.py
python3 scanner/analyze_double_bottom_aa_tradable_blockers.py
python3 scanner/run_preflight_branch_ceiling_audit.py
python3 scanner/run_tradable_candidate_ceiling_audit.py
python3.11 scanner/run_double_family_tradable_rescue.py --families double_bottoms,double_tops --shortlist-size 12
python3 scanner/build_chapter_governance_matrix.py
python3.11 scanner/validate_final_chapters_manifest.py
```

Manifest validation phải fail nếu preflight/governance matrix thiếu, sai policy id, hoặc không phủ đủ chapter final.
