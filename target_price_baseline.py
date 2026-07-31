"""목표주가 탐지 현황 측정 스크립트 (읽기 전용 / 파이프라인 코드 미수정).

reports/ 아래 각 폴더에 대해 실제 파이프라인과 동일한 경로로
  automation.pipeline.report_bundles_from_directory -> readers.read_file
  -> price.indicator.extract_target_price
를 돌리고, 결과를 output/target_price_baseline.md 로 저장한다.

실행 (repo 루트에서):
    .venv\\Scripts\\python.exe target_price_baseline.py
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation.pipeline import report_bundles_from_directory  # noqa: E402
from price.indicator import TARGET_KEYWORDS, extract_target_price  # noqa: E402
from readers import read_file  # noqa: E402

CONTEXT_RADIUS = 3
CLASSIFY_RADIUS = 8

# 목표주가를 뜻할 가능성이 높은 표현.
# '목표가' 는 뒤에 조사/숫자/콜론이 붙는 경우만 (— "제시된 목표가 실제 공시" 같은
# '목표' + 주격조사 '가' 오탐을 배제).
HEADING_RE = re.compile(
    r"목표\s*주가|적정\s*주가|적정\s*가치|적정\s*주당|목표\s*시총|목표\s*시가총액"
    r"|target\s*price|price\s*target|상승여력|upside|밸류에이션\s*결과|valuation\s*summary"
    r"|목표가\s*(?:[:：]|[0-9]|₩|\$|산정|는|은|를|의|\()",
    re.IGNORECASE,
)
# 넓은 문맥 표시용 (사람이 읽고 판단하는 용도)
CONTEXT_RE = re.compile(r"목표|적정|target|valuation|per|pbr", re.IGNORECASE)
PRICE_RE = re.compile(
    r"(?:[$＄₩]\s*[0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|(?:[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:원|KRW|USD|달러|만원|억원|조원))"
    r"|(?:[0-9]{1,3}(?:,[0-9]{3})+)",
    re.IGNORECASE,
)
# 추출 희박 판정 기준: 원본 1KB 당 추출 글자수
SPARSE_PER_KB = 1.5

# ---------------------------------------------------------------------------
# 사람이 원문 문맥을 직접 읽고 확정한 분류.
# 자동 분류는 아래 auto 칼럼으로 따로 남기고, 최종 판단은 이 표를 따른다.
# ---------------------------------------------------------------------------
VERDICTS: dict[str, tuple[str, str, str]] = {
    "메가스터디교육": (
        "(c) 원문에 목표가 없음", "높음",
        "pdf 47쪽 18,655자 + xlsx 54,764자 + 녹음 13,116자로 추출은 충분한데 "
        "목표주가/적정주가/상승여력 계열 표현이 단 1건도 없음. 고치면 안 되는 케이스.",
    ),
    "삼천당제약": (
        "(c) 원문에 목표가 없음", "높음",
        "pptx 텍스트 도형 502개·미디어 10%로 추출 양호(39,588자). 유일한 관련 진술이 "
        "'정확한 적정가치를 산정하긴 어렵지만'(148줄)으로 발표자가 명시적으로 산정을 안 함. "
        "자동분류가 (a)로 본 219줄 '제시된 목표가 실제 공시'는 '목표'+주격조사 '가' 오탐.",
    ),
    "사피엔반도체 (김도현)": (
        "(c) 원문에 목표가 없음", "중간",
        "'스마트글래스 산업 분석' 산업 자료. pdf 34쪽 전부 이미지지만 텍스트 레이어가 있어 "
        "15,957자 추출됨. 목표가 계열 표현 0건. 개별 종목 목표가를 다루는 자료가 아님.",
    ),
    "에스엔시스": (
        "(c) 원문에 목표가 없음", "중간",
        "pptx는 미디어 84%로 희박(9,036자)하지만, 발표자 녹음 txt 13,194자에도 목표주가 "
        "언급이 전혀 없음. 녹음에 없다는 점이 (c)의 근거.",
    ),
    "삼성SDI": (
        "해결됨 — (a) 키워드-숫자 줄 분리였음", "확정",
        "Slide 53 '증권사별 목표 주가 (2026년도)' 아래 별도 줄의 LS증권 531,000원 / "
        "IM증권 800,000원 / 한화투자증권 430,000원. 줄 분리 대응 + "
        "attached_to_identifier 오탐 수정으로 531,000원 탐지. "
        "발표자 본인 목표가가 아니므로 '증권사 컨센서스' 라벨이 붙는다.",
    ),
    "클래시스": (
        "(e) 텍스트 추출 희박 - 판정 불가", "-",
        "pptx 2개 모두 미디어 92~94%, 26~30장에 텍스트 도형이 42~50개뿐 "
        "(추출 6,736 / 5,755자). 목표가 유무를 텍스트만으로 판정할 수 없음. OCR 필요.",
    ),
    "사피엔반도체 (박승주)": (
        "탐지 성공", "-",
        "₩62,000 (base, '1차 목표가 ₩62,000 (Base Case 중단)'). "
        "다만 자료 내에 현대차증권 적정주가 약 4.7만원, Bull 6.6만~8.9만원 등이 혼재해 "
        "대표값 선택이 맞는지 별도 확인 권장.",
    ),
    "한중엔시에스": (
        "해결됨 — 시나리오 표 인식", "확정",
        "이전에는 노트 산문에서 61,000원(base)만 잡았고 덱의 시나리오 표는 "
        "라벨과 금액이 별도 줄이라 전부 놓쳤다. 줄 분리 대응 후 "
        "Bear ₩37,000 / Base ₩61,000 / Bull ₩97,000 을 모두 인식해 "
        "0.25/0.50/0.25 가중평균 64,000원(weighted_average)이 나온다.",
    ),
    "스피어": (
        "(e) 텍스트 추출 희박 - 판정 불가", "-",
        "20장 pptx에서 3,018자만 추출(미디어 92%, 그림 79개). OCR 없이는 판정 불가.",
    ),
    "이수페타시스": (
        "(e) 텍스트 추출 완전 실패", "확정",
        "이수페타시스 분석.pdf 21쪽 전부 이미지, 추출 텍스트 0자. "
        "폴더 전체 입력이 이 파일 하나뿐이라 파이프라인에 들어가는 텍스트가 아예 없음. "
        "목표주가 이전에 요약 자체가 불가능한 상태.",
    ),
    "노타": (
        "해결됨 — (a) 키워드-숫자 줄 분리였음", "확정",
        "Page 24 '목표주가 벨류에이션 산정' 아래 2026년 45,000원 / 2027년 55,000원 / "
        "2028년 66,000원. 줄 분리 대응으로 최근년도인 45,000원을 탐지. "
        "연도별 목표가를 시나리오처럼 다룰지는 별도 판단 필요.",
    ),
    "보로노이": (
        "(e) 텍스트 추출 희박 - 판정 불가", "-",
        "45장 pptx가 미디어 98%(65MB), 추출 14,787자. 녹음 docx에도 목표가 없음. "
        "'최초의 목표가 이렇게'(114줄)는 조사 오탐. OCR 없이는 (c) 확정 불가.",
    ),
}


# ---------------------------------------------------------------------------
# main.py:189 _gather_text 를 그대로 옮긴 것 (main 임포트 부작용 회피용).
# ---------------------------------------------------------------------------
def gather_text(file_paths: list[str], base_dir: Path) -> tuple[str, list[str], list[dict]]:
    chunks: list[str] = []
    used: list[str] = []
    stats: list[dict] = []
    for file_path in file_paths:
        path = Path(file_path)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if not path.exists():
            chunks.append(f"[file not found: {file_path}]")
            continue
        try:
            text = read_file(path)
            error = ""
        except Exception as e:  # noqa: BLE001 - 원본과 동일하게 광범위 캐치
            chunks.append(f"[{path.name} read failed: {e}]")
            text, error = "", str(e)
        size = path.stat().st_size
        stats.append({
            "name": path.name,
            "size": size,
            "chars": len(text),
            "per_kb": (len(text) / (size / 1024)) if size else 0.0,
            "error": error,
            "media_pct": pptx_media_pct(path) if path.suffix.lower() == ".pptx" else None,
        })
        if text.strip():
            chunks.append(f"### File: {path.name}\n{text}")
            used.append(path.name)
    return "\n\n".join(chunks), used, stats


def pptx_media_pct(path: Path) -> float | None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            media = sum(i.file_size for i in infos if i.filename.startswith("ppt/media/"))
            total = sum(i.file_size for i in infos)
        return media / total * 100 if total else None
    except Exception:  # noqa: BLE001
        return None


def has_target_keyword(line: str) -> bool:
    low = line.lower()
    return any(keyword.lower() in low for keyword in TARGET_KEYWORDS)


def pptx_coverage(path: Path) -> dict | None:
    """리더가 놓치는 그룹 도형 / 차트 텍스트를 측정한다.

    readers/reader.py:33 은 shape.has_text_frame 과 has_table 만 처리하고
    그룹 도형에 재귀하지 않으며 차트도 읽지 않는다.
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        return None
    try:
        prs = Presentation(str(path))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    missed_group: list[str] = []
    missed_chart: list[str] = []
    group_shapes = 0
    chart_shapes = 0

    def walk_group(shape) -> None:
        nonlocal group_shapes
        for sub in shape.shapes:
            if sub.shape_type == MSO_SHAPE_TYPE.GROUP:
                group_shapes += 1
                walk_group(sub)
                continue
            if getattr(sub, "has_text_frame", False):
                for para in sub.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        missed_group.append(line)
            if getattr(sub, "has_table", False):
                try:
                    for row in sub.table.rows:
                        for cell in row.cells:
                            if cell.text.strip():
                                missed_group.append(cell.text.strip())
                except (AttributeError, ValueError):
                    pass

    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                group_shapes += 1
                walk_group(shape)
            if getattr(shape, "has_chart", False):
                chart_shapes += 1
                try:
                    chart = shape.chart
                    for cat in chart.plots[0].categories:
                        if cat is not None and str(cat).strip():
                            missed_chart.append(str(cat).strip())
                    for series in chart.series:
                        if getattr(series, "name", None):
                            missed_chart.append(str(series.name).strip())
                except Exception:  # noqa: BLE001
                    pass

    return {
        "group_shapes": group_shapes,
        "chart_shapes": chart_shapes,
        "missed_group": missed_group,
        "missed_chart": missed_chart,
        "missed_group_target": [x for x in missed_group if HEADING_RE.search(x)],
        "missed_chart_target": [x for x in missed_chart if HEADING_RE.search(x)],
    }


def classify_failure(lines: list[str], coverage_hits: int, sparse: bool, empty: bool) -> tuple[str, str]:
    """실패 원인 1차 자동 분류(제안). 최종 판단은 VERDICTS 를 따른다."""
    if empty:
        return "(e) 텍스트 추출 완전 실패", "추출 텍스트가 0자 — 목표가 판정 이전의 문제"

    heading_idx = [i for i, line in enumerate(lines) if HEADING_RE.search(line)]

    if heading_idx:
        for i in heading_idx:
            if PRICE_RE.search(lines[i]):
                return ("(d) 기타",
                        f"목표가 표현과 가격형 숫자가 같은 줄({i})에 있는데도 탐지 실패 "
                        f"-> rejection 사유 확인 필요")
        for i in heading_idx:
            near = lines[max(0, i - CLASSIFY_RADIUS) : i + CLASSIFY_RADIUS + 1]
            if any(PRICE_RE.search(line) for line in near):
                return ("(a) 키워드-숫자 줄 분리",
                        f"목표가 표현이 줄 {i}에 있고 가격형 숫자는 ±{CLASSIFY_RADIUS}줄 이내 "
                        f"다른 줄에 있음 (indicator.py:204 는 같은 줄만 매칭)")
        if coverage_hits > 0:
            return ("(b) 그룹도형/차트 텍스트 유실",
                    f"목표가 표현은 있으나 숫자 없음. 리더가 놓친 그룹/차트 텍스트 {coverage_hits}건")
        if sparse:
            return ("(e) 텍스트 추출 희박", "목표가 표현은 있으나 숫자 없음 + 추출 희박")
        return "(d) 기타", "목표가 표현은 있으나 인접 범위에 가격형 숫자 없음"

    if coverage_hits > 0:
        return ("(b) 그룹도형/차트 텍스트 유실",
                f"추출 텍스트에 목표가 표현 없음. 놓친 그룹/차트 텍스트에 {coverage_hits}건 발견")
    if sparse:
        return ("(e) 텍스트 추출 희박",
                "목표가 표현 없음 + 추출이 원본 대비 희박 -> (c)로 단정 불가")
    return ("(c) 원문에 애초에 목표가 없음",
            "추출은 충분한데 목표주가/적정주가/상승여력 계열 표현이 전혀 없음")


def context_blocks(lines: list[str], radius: int = CONTEXT_RADIUS):
    hits = [i for i, line in enumerate(lines) if CONTEXT_RE.search(line)]
    blocks = []
    used = set()
    for i in hits:
        start, end = max(0, i - radius), min(len(lines), i + radius + 1)
        if (start, end) in used:
            continue
        used.add((start, end))
        blocks.append((start, lines[start:end], i))
    return blocks


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def verdict_key(bundle) -> str:
    if bundle.title == "사피엔반도체":
        return f"사피엔반도체 ({bundle.author})"
    return bundle.title


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    output_path = REPO_ROOT / "output" / "target_price_baseline.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundles = report_bundles_from_directory(REPO_ROOT / "reports")
    print(f"[info] {len(bundles)}개 폴더")

    out = io.StringIO()
    out.write("# 목표주가 탐지 baseline\n\n")
    out.write(f"- 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    out.write("- 경로: `report_bundles_from_directory` → `readers.read_file` → "
              "`price.indicator.extract_target_price`\n")
    out.write("- 파이프라인 코드는 수정하지 않은 상태에서 측정 (읽기 전용)\n")
    out.write("- 3장 최종 분류는 자동 분류가 아니라 원문 문맥을 직접 읽고 확정한 것\n")

    rows: list[str] = []
    file_rows: list[str] = []
    details: list[str] = []
    failures: list[str] = []
    auto_tally: dict[str, list[str]] = {}

    for bundle in bundles:
        label = f"{bundle.author}, {bundle.title}"
        print(f"[read] {label}")
        text, used_files, stats = gather_text(bundle.files, REPO_ROOT)
        lines = text.splitlines()
        target = extract_target_price(text)

        for st in stats:
            flag = ""
            if st["chars"] == 0:
                flag = "**추출 0**"
            elif st["per_kb"] < SPARSE_PER_KB and Path(st["name"]).suffix.lower() in {".pptx", ".pdf"}:
                flag = "추출 희박"
            media = f"{st['media_pct']:.0f}%" if st["media_pct"] is not None else "-"
            file_rows.append(
                f"| {md_escape(label)} | {md_escape(st['name'])} | {st['size']:,} | "
                f"{st['chars']:,} | {st['per_kb']:.2f} | {media} | {flag} |"
            )

        empty = not text.strip()
        sparse = any(
            st["chars"] == 0
            or (st["per_kb"] < SPARSE_PER_KB and Path(st["name"]).suffix.lower() in {".pptx", ".pdf"})
            for st in stats
        )

        coverage_reports = []
        for file_path in bundle.files:
            p = Path(file_path)
            if p.suffix.lower() != ".pptx":
                continue
            cov = pptx_coverage(p)
            if cov:
                coverage_reports.append((p.name, cov))
        coverage_hits = sum(
            len(c.get("missed_group_target", [])) + len(c.get("missed_chart_target", []))
            for _, c in coverage_reports if "error" not in c
        )

        detected = target.display if target else "**None**"
        rep = (target.representative_label or "-") if target else "-"
        src = md_escape(target.source[:100]) if target else "-"
        rejected_count = len(target.rejected_candidates) if target else 0
        rows.append(
            f"| {md_escape(label)} | {detected} | {rep} | {src} | {rejected_count} | "
            f"{len(lines):,} | {len(text):,} |"
        )

        details.append(f"\n### {label}\n\n")
        details.append(f"- 입력: {', '.join(used_files) or '**(추출된 텍스트 없음)**'}\n")
        details.append(f"- 추출 텍스트: {len(lines):,}줄 / {len(text):,}자\n")
        if target:
            details.append(f"- **탐지값**: `{target.display}` (value={target.value:,.2f}, "
                           f"representative=`{target.representative_label or '-'}`, "
                           f"is_base={target.is_base})\n")
            details.append(f"- 근거 줄: `{md_escape(target.source[:300])}`\n")
            if target.scenarios:
                details.append("- 시나리오:\n")
                for sc in target.scenarios:
                    details.append(f"  - `{sc.label}` = {sc.display} ({sc.value:,.2f}) "
                                   f"← `{md_escape(sc.source[:140])}`\n")
            else:
                details.append("- 시나리오: **없음** (bear/base/bull 라벨 매칭 실패)\n")
        else:
            details.append("- **탐지값**: None\n")

        if target and target.rejected_candidates:
            details.append(f"- rejected_candidates ({len(target.rejected_candidates)}건):\n\n")
            details.append("  | display | reason | source |\n  |---|---|---|\n")
            for rc in target.rejected_candidates[:30]:
                details.append(f"  | `{md_escape(rc.display)}` | `{rc.reason}` | "
                               f"{md_escape(rc.source[:100])} |\n")
            if len(target.rejected_candidates) > 30:
                details.append(f"\n  _…외 {len(target.rejected_candidates) - 30}건_\n")
        elif target:
            details.append("- rejected_candidates: 없음\n")
        else:
            details.append("- rejected_candidates: **후보 수집 0** "
                           "(`require_target_line=True` 에서 전량 탈락)\n")

        for fname, cov in coverage_reports:
            if "error" in cov:
                details.append(f"- 리더 커버리지 `{fname}`: 열기 실패 ({cov['error']})\n")
                continue
            details.append(
                f"- 리더 커버리지 `{fname}`: 그룹도형 {cov['group_shapes']}개 / "
                f"차트 {cov['chart_shapes']}개 → 유실 {len(cov['missed_group'])}줄(그룹) + "
                f"{len(cov['missed_chart'])}줄(차트), 그중 목표가 관련 "
                f"**{len(cov['missed_group_target']) + len(cov['missed_chart_target'])}줄**\n"
            )

        if target is None:
            category, rationale = classify_failure(lines, coverage_hits, sparse, empty)
            auto_tally.setdefault(category, []).append(label)
            failures.append(f"\n### {label}\n\n")
            failures.append(f"- 자동 분류(제안): {category}\n")
            failures.append(f"- 근거: {rationale}\n")
            blocks = context_blocks(lines)
            if not blocks:
                failures.append("\n_'목표/적정/target/valuation/PER/PBR' 키워드가 "
                                "추출 텍스트에 전혀 없음._\n")
            else:
                failures.append(f"\n키워드 문맥 {len(blocks)}블록 (앞뒤 {CONTEXT_RADIUS}줄, "
                                f"`>>`=키워드 줄, `$`=가격형 숫자 포함):\n\n")
                for start, block, hit in blocks[:20]:
                    failures.append("```\n")
                    for offset, line in enumerate(block):
                        n = start + offset
                        mark = ">>" if n == hit else ("$ " if PRICE_RE.search(line) else "  ")
                        failures.append(f"{mark} {n:>6}: {line[:200]}\n")
                    failures.append("```\n\n")
                if len(blocks) > 20:
                    failures.append(f"_…외 {len(blocks) - 20}블록 생략_\n\n")
        else:
            auto_tally.setdefault("탐지 성공", []).append(label)

    out.write("\n## 1. 폴더별 탐지 결과\n\n")
    out.write("| 폴더 | 탐지값 | representative | 근거 줄 | rejected | 줄수 | 글자수 |\n")
    out.write("|---|---|---|---|---|---|---|\n")
    out.write("\n".join(rows))

    out.write("\n\n## 2. 파일별 텍스트 추출량\n\n")
    out.write("`글자/KB` 가 낮을수록 원본 대비 텍스트가 적게 뽑혔다는 뜻 "
              f"(pptx/pdf 에서 {SPARSE_PER_KB} 미만이면 이미지 기반 의심).\n\n")
    out.write("| 폴더 | 파일 | 바이트 | 추출 글자 | 글자/KB | pptx 미디어 비중 | 판정 |\n")
    out.write("|---|---|---|---|---|---|---|\n")
    out.write("\n".join(file_rows))

    out.write("\n\n## 3. 폴더별 상세\n")
    out.write("".join(details))

    out.write("\n\n## 4. 탐지 실패 폴더의 키워드 문맥\n")
    out.write("".join(failures) if failures else "\n_없음._\n")

    out.write("\n\n## 5. 최종 분류 (사람이 문맥 확인 후 확정)\n\n")
    out.write("| 폴더 | 최종 분류 | 확신도 | 근거 |\n|---|---|---|---|\n")
    order = {"탐지 성공": 0, "해결됨 — 시나리오 표 인식": 1,
             "해결됨 — (a) 키워드-숫자 줄 분리였음": 2,
             "(e) 텍스트 추출 완전 실패": 3, "(e) 텍스트 추출 희박 - 판정 불가": 4,
             "(c) 원문에 목표가 없음": 5}
    verdict_items = []
    for bundle in bundles:
        key = verdict_key(bundle)
        verdict = VERDICTS.get(key)
        if not verdict:
            continue
        verdict_items.append((order.get(verdict[0], 9), f"{bundle.author}, {bundle.title}", verdict))
    for _, label, (category, confidence, note) in sorted(verdict_items, key=lambda x: (x[0], x[1])):
        out.write(f"| {md_escape(label)} | **{category}** | {confidence} | {md_escape(note)} |\n")

    out.write("\n### 자동 분류 집계 (참고용 — 최종 분류와 다를 수 있음)\n\n")
    out.write("| 자동 분류 | 수 | 폴더 |\n|---|---|---|\n")
    for category in sorted(auto_tally):
        items = auto_tally[category]
        out.write(f"| {category} | {len(items)} | {md_escape('; '.join(items))} |\n")

    out.write(
        "\n> **(c) 로 확정된 폴더는 '고치면 안 되는' 케이스다.** 탐지 로직을 느슨하게 해서 "
        "여기에 값이 생기면 개선이 아니라 false positive다. 회귀 검증 시 이 폴더들은 "
        "계속 None 이어야 한다.\n>\n"
        "> **(e) 는 목표가 로직 문제가 아니라 텍스트 추출 문제다.** 여기서 값이 안 나오는 건 "
        "정규식이나 LLM 프롬프트를 고쳐서 해결되지 않는다.\n"
    )

    output_path.write_text(out.getvalue(), encoding="utf-8")
    print(f"[done] {output_path}")
    print("\n=== 자동 분류 요약 ===")
    for category in sorted(auto_tally):
        print(f"  {category}: {len(auto_tally[category])}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
