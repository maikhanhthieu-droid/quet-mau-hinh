from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _is_vi(language: str) -> bool:
    return str(language).strip().lower() == "vi"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_dotenv_if_present() -> None:
    def _parse_line(line: str) -> Optional[Tuple[str, str]]:
        s = line.strip()
        if not s or s.startswith("#"):
            return None
        if s.startswith("export "):
            s = s[len("export ") :].strip()
        if "=" not in s:
            return None
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        return (k, v)

    repo_root = Path(__file__).resolve().parent.parent
    dotenv_path = repo_root / ".env"
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        kv = _parse_line(line)
        if not kv:
            continue
        k, v = kv
        if k not in os.environ:
            os.environ[k] = v


def _deepseek_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout_s: int = 120,
) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = {"model": model, "messages": messages, "temperature": 0.2}
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"DeepSeek HTTPError {getattr(e, 'code', '?')}: {msg}")
    except URLError as e:
        raise RuntimeError(f"DeepSeek URLError: {e}")

    try:
        return str(payload["choices"][0]["message"]["content"])
    except Exception:
        raise RuntimeError(f"Unexpected DeepSeek response shape: {payload}")


def _normalize_commentary(text: str, *, language: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    if _is_vi(language):
        aliases = {
            "nhận xét": "### Nhận xét chính",
            "so với": "### So với mốc tham chiếu",
            "tham chiếu": "### So với mốc tham chiếu",
            "lưu ý": "### Lưu ý về chất lượng mẫu",
            "chất lượng mẫu": "### Lưu ý về chất lượng mẫu",
            "hàm ý": "### Hàm ý sử dụng",
            "sử dụng": "### Hàm ý sử dụng",
        }
        primary_heading = "### Nhận xét chính"
    else:
        aliases = {
            "main": "### Main Takeaways",
            "benchmark": "### Versus Bulkowski Baseline",
            "baseline": "### Versus Bulkowski Baseline",
            "sample": "### Sample Quality Notes",
            "quality": "### Sample Quality Notes",
            "usage": "### Usage Implications",
            "implication": "### Usage Implications",
        }
        primary_heading = "### Main Takeaways"

    lines: List[str] = []
    seen = set()
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("###"):
            lowered = s.lower()
            normalized = s
            for key, target in aliases.items():
                if key in lowered:
                    normalized = target
                    break
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(normalized)
        else:
            lines.append(line.rstrip())

    normalized = "\n".join(lines).strip()
    if primary_heading not in normalized:
        normalized = primary_heading + "\n\n" + normalized
    return normalized.strip() + "\n"


def _extract_numeric_tokens(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", str(text or ""))


def _normalize_numeric_token(token: str) -> Optional[float]:
    try:
        return round(float(token), 6)
    except Exception:
        return None


def _validate_commentary_numbers(commentary: str, core_md: str) -> Tuple[bool, List[str]]:
    allowed_values = {
        value
        for token in _extract_numeric_tokens(core_md)
        for value in [_normalize_numeric_token(token)]
        if value is not None
    }
    unsupported: List[str] = []
    for token in _extract_numeric_tokens(commentary):
        value = _normalize_numeric_token(token)
        if value is None:
            continue
        if value not in allowed_values:
            unsupported.append(token)
    return (len(unsupported) == 0, sorted(set(unsupported)))


def _style_fingerprint(style_guide: str, model: str) -> str:
    return _sha256_text("book_v2_phase3_style_v1\n" + model + "\n" + style_guide)


def _build_commentary_prompt(
    *,
    payload: Dict[str, Any],
    core_md: str,
    style_guide: str,
    language: str,
    forbid_digits: bool = False,
    retry_note: Optional[str] = None,
) -> List[Dict[str, str]]:
    summary = payload.get("summary") or {}
    governance = payload.get("governance") or {}
    benchmark = payload.get("benchmark") or {}
    if _is_vi(language):
        system = (
            "Bạn là biên tập viên cho một tài liệu nghiên cứu mô hình giá. "
            "Hãy viết tiếng Việt, giọng điệu ngắn gọn, thực dụng, theo tinh thần của một sổ tay nghiên cứu pattern reference, "
            "nhưng không sao chép nguyên văn hay bắt chước trực tiếp câu chữ có bản quyền. "
            "Tuyệt đối không bịa dữ kiện, không thêm số mới, không thay đổi governance status."
        )
        user = (
            "Hãy viết phần commentary tùy chọn cho một chapter Book v2.\n\n"
            "Style guide:\n"
            f"{style_guide}\n\n"
            "Fact guardrails:\n"
            "- Chỉ được dùng facts và numbers đã có trong chapter core.\n"
            "- Không được thêm ranking mới hoặc quyết định strategy mới.\n"
            "- Nếu pattern đang research_only/recalibrate/watchlist/retired thì commentary phải tôn trọng đúng lane đó.\n\n"
            "Chapter metadata:\n"
            f"- pattern_key: {summary.get('pattern_key')}\n"
            f"- bulkowski_name: {summary.get('bulkowski_name')}\n"
            f"- phase3_status: {governance.get('phase3_status')}\n"
            f"- strategy_gate: {governance.get('strategy_gate')}\n"
            f"- benchmark_status: {benchmark.get('benchmark_status')}\n\n"
            "Chapter core markdown:\n"
            f"{core_md}\n\n"
            "Yêu cầu đầu ra:\n"
            "- Dùng đúng 4 headings cấp 3:\n"
            "  ### Nhận xét chính\n"
            "  ### So với mốc tham chiếu\n"
            "  ### Lưu ý về chất lượng mẫu\n"
            "  ### Hàm ý sử dụng\n"
            "- Viết ngắn, mỗi mục một đoạn ngắn.\n"
            "- Không lặp lại toàn bộ bảng số.\n"
            "- Không dùng bullet list.\n"
            + ("- Không dùng bất kỳ chữ số nào trong đầu ra.\n" if forbid_digits else "- Không đưa thêm bất kỳ con số nào không có trong chapter core.\n")
            + (f"- Ghi chú sửa draft trước: {retry_note}\n" if retry_note else "")
        )
    else:
        system = (
            "You are the editorial layer for a chart pattern research monograph. "
            "Write concise English in the tone of a disciplined reference handbook. "
            "Do not invent facts, do not introduce new numeric claims, and do not override governance status."
        )
        user = (
            "Write the optional commentary layer for a Book v2 chapter.\n\n"
            "Style guide:\n"
            f"{style_guide}\n\n"
            "Fact guardrails:\n"
            "- Use only facts and numbers already present in the chapter core.\n"
            "- Do not add new rankings or strategy decisions.\n"
            "- Respect the current governance lane for research_only/recalibrate/watchlist/retired.\n\n"
            "Chapter metadata:\n"
            f"- pattern_key: {summary.get('pattern_key')}\n"
            f"- bulkowski_name: {summary.get('bulkowski_name')}\n"
            f"- phase3_status: {governance.get('phase3_status')}\n"
            f"- strategy_gate: {governance.get('strategy_gate')}\n"
            f"- benchmark_status: {benchmark.get('benchmark_status')}\n\n"
            "Chapter core markdown:\n"
            f"{core_md}\n\n"
            "Output requirements:\n"
            "- Use exactly these four level-3 headings:\n"
            "  ### Main Takeaways\n"
            "  ### Versus Bulkowski Baseline\n"
            "  ### Sample Quality Notes\n"
            "  ### Usage Implications\n"
            "- Keep each section to one short paragraph.\n"
            "- Do not rewrite the numeric tables.\n"
            "- Do not use bullet lists.\n"
            + ("- Do not use any digits in the output.\n" if forbid_digits else "- Do not introduce any number that is not already in the chapter core.\n")
            + (f"- Revision note from previous draft: {retry_note}\n" if retry_note else "")
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _namespace_markdown_assets(md: str, *, pattern_key: str) -> str:
    return re.sub(r"\]\((figures/[^)]+)\)", rf"]({pattern_key}/\1)", md)


def _render_final_chapter(core_md: str, commentary_md: str, *, pattern_key: str, language: str) -> str:
    core = core_md.strip()
    commentary = commentary_md.strip()
    core = _namespace_markdown_assets(core, pattern_key=pattern_key)
    if not commentary:
        return core + "\n"
    heading = "## Nhận xét biên tập" if _is_vi(language) else "## Commentary"
    return core + "\n\n" + heading + "\n\n" + commentary + "\n"


def _normalize_market_report_md(market_report_md: str) -> str:
    lines = market_report_md.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def _render_book(
    *,
    title: str,
    generated_at: str,
    market_report_md: Optional[str],
    chapter_rows: Sequence[Dict[str, Any]],
    ai_enabled: bool,
    language: str,
) -> str:
    vi = _is_vi(language)
    lines: List[str] = []
    lines.append("---")
    lines.append(f'title: "{title}"')
    lines.append(f'lang: "{"vi-VN" if vi else "en-US"}"')
    lines.append(f'date: "{generated_at[:10]}"')
    lines.append("---")
    lines.append("")
    lines.append("# Lời mở đầu" if vi else "# Foreword")
    lines.append("")
    lines.append(
        (
            "Tài liệu này là bản Book v2 của hệ thống nghiên cứu pattern tại Việt Nam. "
            "Nội dung cốt lõi được sinh từ payload deterministic của scanner, benchmark và governance layer. "
            "Nếu có commentary AI, phần đó chỉ đóng vai trò chú giải biên tập."
        )
        if vi
        else (
            "This document is Book v2 for the Vietnam pattern research system. "
            "The core content is generated from deterministic scanner, benchmark, and governance payloads. "
            "If AI commentary is present, it serves only as an editorial layer."
        )
    )
    lines.append("")
    lines.append(f"- generated_at: `{generated_at}`")
    lines.append(f"- ai_commentary_enabled: `{str(bool(ai_enabled)).lower()}`")
    lines.append(f"- language: `{language}`")
    lines.append("")
    lines.append("\\newpage")
    lines.append("")
    if market_report_md:
        lines.append("# Tổng quan thị trường Việt Nam" if vi else "# Vietnam Market Overview")
        lines.append("")
        lines.append(_normalize_market_report_md(market_report_md))
        lines.append("")
        lines.append("\\newpage")
        lines.append("")
    lines.append("# Pattern Monographs" if not vi else "# Pattern Monograph")
    lines.append("")
    for row in chapter_rows:
        lines.append(row["chapter_final_md"].strip())
        lines.append("")
        lines.append("\\newpage")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _try_build_pdf(*, book_md_path: Path, out_pdf_path: Path, mainfont: Optional[str]) -> Tuple[bool, str]:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return (False, "pandoc not found; generated Markdown only.")

    pdf_engine = None
    for candidate in ["tectonic", "xelatex", "lualatex", "pdflatex"]:
        if shutil.which(candidate):
            pdf_engine = candidate
            break
    if not pdf_engine:
        return (False, "No PDF engine found (tectonic/xelatex/lualatex/pdflatex). Generated Markdown only.")

    book_dir = str(book_md_path.parent.resolve())
    preamble_path = book_md_path.parent / "_pandoc_preamble.tex"
    _write_text(
        preamble_path,
        "\n".join(
            [
                "% Auto-generated by scanner/build_book_v2.py",
                "\\usepackage[a4paper,left=2.1cm,right=2.1cm,top=1.6cm,bottom=1.8cm]{geometry}",
                "\\usepackage{etoolbox}",
                "\\usepackage{graphicx}",
                "\\usepackage{titlesec}",
                "\\raggedbottom",
                "\\sloppy",
                "\\setlength{\\emergencystretch}{3em}",
                "\\setlength{\\tabcolsep}{1.5pt}",
                "\\renewcommand{\\arraystretch}{0.84}",
                "\\setlength{\\LTpre}{2pt}",
                "\\setlength{\\LTpost}{0pt}",
                "\\setlength{\\LTleft}{0pt}",
                "\\setlength{\\LTright}{0pt}",
                "\\titlespacing*{\\section}{0pt}{0.6\\baselineskip}{0.35\\baselineskip}",
                "\\titlespacing*{\\subsection}{0pt}{0.45\\baselineskip}{0.25\\baselineskip}",
                "\\titlespacing*{\\subsubsection}{0pt}{0.35\\baselineskip}{0.2\\baselineskip}",
                "\\setkeys{Gin}{width=0.92\\linewidth,height=0.42\\textheight,keepaspectratio}",
                "\\AtBeginEnvironment{longtable}{\\scriptsize}",
                "\\AtBeginEnvironment{table}{\\footnotesize}",
                "",
            ]
        )
        + "\n",
    )

    cmd = [
        pandoc,
        book_md_path.name,
        "-o",
        str(out_pdf_path.resolve()),
        f"--pdf-engine={pdf_engine}",
        "--resource-path",
        book_dir,
        "--toc",
        "--toc-depth=2",
        "-H",
        str(preamble_path.resolve()),
    ]
    if mainfont:
        cmd.extend(["-V", f"mainfont={mainfont}"])

    try:
        subprocess.run(cmd, check=True, cwd=book_dir)
    except Exception as e:
        return (False, f"pandoc failed (engine={pdf_engine}): {e}")
    return (True, f"Wrote PDF: {str(out_pdf_path.resolve())}")


def build_book_v2(
    *,
    monograph_dir: Path,
    out_dir: Path,
    market_report_md: Optional[Path],
    style_guide_path: Path,
    patterns: Optional[List[str]],
    skip_ai: bool,
    deepseek_api_key: Optional[str],
    deepseek_base_url: str,
    deepseek_model: str,
    timeout_s: int,
    skip_pdf: bool,
    pdf_mainfont: Optional[str],
    language: str,
) -> Dict[str, Any]:
    index = _read_json(monograph_dir / "index.json")
    style_guide = style_guide_path.read_text(encoding="utf-8")
    style_fp = _style_fingerprint(style_guide, deepseek_model)
    selected = [row for row in index["patterns"] if not patterns or row["pattern_key"] in patterns]
    out_dir.mkdir(parents=True, exist_ok=True)

    chapter_rows: List[Dict[str, Any]] = []
    ai_enabled = bool((not skip_ai) and deepseek_api_key)

    for row in selected:
        pattern_key = str(row["pattern_key"])
        source_dir = monograph_dir / pattern_key
        chapter_dir = out_dir / pattern_key
        chapter_dir.mkdir(parents=True, exist_ok=True)

        payload_path = source_dir / "chapter_payload.json"
        core_path = source_dir / "chapter_core.md"
        payload = _read_json(payload_path)
        core_md = core_path.read_text(encoding="utf-8")

        shutil.copy2(payload_path, chapter_dir / "chapter_payload.json")
        shutil.copy2(core_path, chapter_dir / "chapter_core.md")
        source_figures = source_dir / "figures"
        if source_figures.exists():
            target_figures = chapter_dir / "figures"
            target_figures.mkdir(parents=True, exist_ok=True)
            for img in source_figures.iterdir():
                if img.is_file():
                    shutil.copy2(img, target_figures / img.name)

        prompt_fp = _sha256_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
            + "\n---CORE---\n"
            + core_md
            + "\n---STYLE---\n"
            + style_fp
            + "\n---LANGUAGE---\n"
            + language
        )

        commentary_cache_path = chapter_dir / "chapter_commentary.json"
        commentary_md = ""
        cache_obj: Dict[str, Any] = {}
        if commentary_cache_path.exists():
            try:
                cache_obj = _read_json(commentary_cache_path)
            except Exception:
                cache_obj = {}
        cached_content = str(cache_obj.get("content") or "")
        cache_valid = cache_obj.get("fingerprint") == prompt_fp and bool(cached_content)

        commentary_status = "skipped"
        commentary_error = None
        last_raw_commentary = None
        if ai_enabled:
            if cache_valid:
                commentary_md = cached_content
                commentary_status = "cache"
            else:
                try:
                    last_unsupported: List[str] = []
                    for attempt in range(2):
                        raw = _deepseek_chat_completion(
                            base_url=deepseek_base_url,
                            api_key=str(deepseek_api_key),
                            model=deepseek_model,
                            messages=_build_commentary_prompt(
                                payload=payload,
                                core_md=core_md,
                                style_guide=style_guide,
                                language=language,
                                forbid_digits=(attempt == 1),
                                retry_note=(
                                    "Draft trước đã đưa vào unsupported numeric tokens: "
                                    + ", ".join(last_unsupported[:10])
                                    if attempt == 1 and last_unsupported
                                    else None
                                ),
                            ),
                            timeout_s=timeout_s,
                        )
                        last_raw_commentary = raw
                        normalized = _normalize_commentary(raw, language=language)
                        ok, unsupported = _validate_commentary_numbers(normalized, core_md)
                        if ok:
                            commentary_md = normalized
                            commentary_status = "generated"
                            break
                        last_unsupported = unsupported
                    if commentary_status != "generated":
                        raise RuntimeError(
                            "Commentary introduced unsupported numeric tokens: " + ", ".join(last_unsupported[:10])
                        )
                    _write_json(
                        commentary_cache_path,
                        {
                            "fingerprint": prompt_fp,
                            "generated_at": _utc_now_iso(),
                            "model": deepseek_model,
                            "content": commentary_md,
                        },
                    )
                except Exception as e:
                    commentary_error = str(e)
                    commentary_status = "error"
                    commentary_md = ""
        _write_text(chapter_dir / "chapter_commentary.md", commentary_md)
        if not commentary_cache_path.exists():
            _write_json(
                commentary_cache_path,
                {
                    "fingerprint": prompt_fp,
                    "generated_at": _utc_now_iso(),
                    "model": deepseek_model,
                    "content": commentary_md,
                    "status": commentary_status,
                    "error": commentary_error,
                    "raw_content": last_raw_commentary,
                },
            )
        final_md = _render_final_chapter(core_md, commentary_md, pattern_key=pattern_key, language=language)
        _write_text(chapter_dir / "chapter_final.md", final_md)

        chapter_rows.append(
            {
                **row,
                "commentary_status": commentary_status,
                "commentary_error": commentary_error,
                "chapter_final_md": final_md,
                "chapter_dir": str(chapter_dir.resolve()),
            }
        )

    market_text = market_report_md.read_text(encoding="utf-8") if market_report_md and market_report_md.exists() else None
    book_md = _render_book(
        title="Sách mẫu hình Việt Nam V2" if _is_vi(language) else "Vietnam Pattern Book V2",
        generated_at=_utc_now_iso(),
        market_report_md=market_text,
        chapter_rows=chapter_rows,
        ai_enabled=ai_enabled,
        language=language,
    )
    book_md_path = out_dir / "book_v2.md"
    _write_text(book_md_path, book_md)
    pdf_ok = False
    pdf_msg = "Skipped PDF build."
    pdf_path = None
    if not skip_pdf:
        out_pdf_path = out_dir / "book_v2.pdf"
        pdf_ok, pdf_msg = _try_build_pdf(book_md_path=book_md_path, out_pdf_path=out_pdf_path, mainfont=pdf_mainfont)
        if pdf_ok:
            pdf_path = str(out_pdf_path.resolve())
    summary = {
        "generated_at": _utc_now_iso(),
        "monograph_dir": str(monograph_dir.resolve()),
        "market_report_md": str(market_report_md.resolve()) if market_report_md and market_report_md.exists() else None,
        "style_guide": str(style_guide_path.resolve()),
        "language": language,
        "ai_enabled": ai_enabled,
        "book_md_path": str(book_md_path.resolve()),
        "pdf_generated": pdf_ok,
        "pdf_message": pdf_msg,
        "pdf_path": pdf_path,
        "pattern_count": len(chapter_rows),
        "commentary_status_counts": {
            key: sum(1 for row in chapter_rows if row["commentary_status"] == key)
            for key in sorted({row["commentary_status"] for row in chapter_rows})
        },
        "patterns": [
            {
                "pattern_key": row["pattern_key"],
                "phase3_status": row["phase3_status"],
                "strategy_gate": row["strategy_gate"],
                "benchmark_status": row["benchmark_status"],
                "commentary_status": row["commentary_status"],
                "commentary_error": row["commentary_error"],
                "chapter_dir": row["chapter_dir"],
            }
            for row in chapter_rows
        ],
    }
    _write_json(out_dir / "book_v2_meta.json", summary)
    return summary


def main() -> None:
    _load_dotenv_if_present()
    parser = argparse.ArgumentParser(description="Build Book v2 final chapters and optional DeepSeek commentary.")
    parser.add_argument("--monograph-dir", required=True, help="Phase 2 deterministic monograph directory")
    parser.add_argument("--out-dir", required=True, help="Output directory for Book v2 final chapters/book")
    parser.add_argument("--market-report-md", default=None, help="Optional market report markdown to prepend")
    parser.add_argument(
        "--style-guide",
        default="docs/publication/book-v2/commentary-style-guide.md",
        help="Commentary style guide markdown",
    )
    parser.add_argument("--patterns", default=None, help="Optional comma-separated pattern list")
    parser.add_argument("--skip-ai", action="store_true", help="Skip DeepSeek commentary generation")
    parser.add_argument("--deepseek-base-url", default=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--deepseek-model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--deepseek-api-key", default=os.getenv("DEEPSEEK_API_KEY"))
    parser.add_argument("--timeout-s", type=int, default=120, help="Timeout per DeepSeek call")
    parser.add_argument("--skip-pdf", action="store_true", help="Skip PDF build even if pandoc exists")
    parser.add_argument("--pdf-mainfont", default=None, help="Optional mainfont for pandoc/xelatex/lualatex")
    parser.add_argument("--language", default="vi", choices=["en", "vi"], help="Output language for final book assembly and commentary")
    args = parser.parse_args()

    patterns = None
    if args.patterns:
        patterns = [part.strip() for part in str(args.patterns).split(",") if part.strip()]

    build_book_v2(
        monograph_dir=Path(args.monograph_dir),
        out_dir=Path(args.out_dir),
        market_report_md=Path(args.market_report_md) if args.market_report_md else None,
        style_guide_path=Path(args.style_guide),
        patterns=patterns,
        skip_ai=bool(args.skip_ai),
        deepseek_api_key=args.deepseek_api_key,
        deepseek_base_url=str(args.deepseek_base_url),
        deepseek_model=str(args.deepseek_model),
        timeout_s=int(args.timeout_s),
        skip_pdf=bool(args.skip_pdf),
        pdf_mainfont=args.pdf_mainfont,
        language=str(args.language),
    )


if __name__ == "__main__":
    main()
