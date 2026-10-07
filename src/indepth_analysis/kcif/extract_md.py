"""PDF → 접근 가능한 텍스트 원본 .md (+ 이미지 추출).

산출물: ``references/KCIF_md/{published_date}_{rpt_no}_{슬러그}.md``
- frontmatter(title/category/author/published_date/url/pdf)
- 페이지 순 텍스트, 페이지별 이미지는 페이지 끝에 ``![그림 N](img/…)``
- 이미지는 래스터 XObject만 추출 가능 (금융 리서치의 벡터 차트는 미포착 —
  그 경우 플레이스홀더 없이 텍스트만). 50px 미만·극단 종횡비는 장식으로 스킵.
- 본문 텍스트는 report_texts(FTS)로 미러 → 검색·토픽 스캔의 소스.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

from indepth_analysis.kcif import store
from indepth_analysis.kcif.paths import IMG_DIR, MD_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

MIN_IMG_PX = 50
MAX_ASPECT = 20.0


def _slug(title: str, cap: int = 64) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", title).strip("_")
    return s[:cap] or "report"


def md_path_for(report) -> Path:
    date = report.published_date or "0000-00-00"
    return MD_DIR / f"{date}_{report.external_id}_{_slug(report.title)}.md"


def _extract_images(doc, page, rpt_no: str, page_no: int, counter: list[int]) -> list[str]:
    """페이지의 래스터 이미지를 파일로 저장, md 라인 목록 반환."""
    lines: list[str] = []
    try:
        images = page.get_images(full=True)
    except Exception:
        return lines
    for img in images:
        xref = img[0]
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.width < MIN_IMG_PX or pix.height < MIN_IMG_PX:
                continue
            aspect = max(pix.width, pix.height) / max(1, min(pix.width, pix.height))
            if aspect > MAX_ASPECT:
                continue
            if pix.n - pix.alpha >= 4:  # CMYK 등 → RGB 변환
                pix = fitz.Pixmap(fitz.csRGB, pix)
            counter[0] += 1
            n = counter[0]
            IMG_DIR.mkdir(parents=True, exist_ok=True)
            out = IMG_DIR / f"{rpt_no}_{n:02d}.png"
            pix.save(str(out))
            lines.append(f"![그림 {n} (p.{page_no})](img/{out.name})")
        except Exception:
            logger.debug("image extract failed rpt=%s xref=%s", rpt_no, xref, exc_info=True)
    return lines


def extract_report_md(report, pdf_path) -> str | None:
    """PDF 1건 → .md 파일 생성 + report_texts 적재. 반환: md 절대경로 (실패 None)."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("PDF open failed id=%s: %s", report.id, e)
        return None

    out_path = md_path_for(report)
    body_parts: list[str] = []
    has_text = False
    img_counter = [0]
    try:
        for i, page in enumerate(doc, start=1):
            text = (page.get_text("text") or "").strip()
            if text:
                has_text = True
                body_parts.append(text)
            img_lines = _extract_images(doc, page, str(report.external_id), i, img_counter)
            if img_lines:
                body_parts.append("\n".join(img_lines))
    finally:
        doc.close()

    body = "\n\n".join(body_parts).strip()
    if not has_text:
        logger.warning("PDF empty text id=%s %s", report.id, pdf_path)
        return None

    front = "\n".join([
        "---",
        f"title: {report.title}",
        f"category: {report.category or ''}",
        f"author: {report.author or ''}",
        f"published: {report.published_date or ''}",
        f"url: {report.url}",
        f"pdf: {pdf_path}",
        "---",
        "",
        f"# {report.title}",
        "",
    ])
    MD_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(front + body + "\n", encoding="utf-8")

    # DB 반영: md_path(프로젝트 루트 상대) + 본문 미러(FTS)
    rel = str(out_path.relative_to(PROJECT_ROOT))
    store.upsert_report_text(int(report.id), body, md_path=rel)
    return str(out_path)


def backfill_all(db, source_id: int, *, limit: int | None = None) -> dict:
    """다운로드 완료 + md 미생성 리포트 전체를 일괄 추출 (초기 674건 백필용)."""
    from indepth_analysis.models.reference import DownloadStatus

    conn = store.get_conn()
    rows = conn.execute(
        "SELECT r.id FROM reports r LEFT JOIN report_texts t ON t.report_id = r.id "
        "WHERE r.source_id = ? AND r.download_status = ? "
        "AND (r.md_path IS NULL OR r.md_path = '' OR t.report_id IS NULL "
        "OR t.text IS NULL OR TRIM(t.text) = '') ORDER BY r.published_date ASC",
        (source_id, DownloadStatus.DOWNLOADED.value),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if limit:
        ids = ids[:limit]
    ok = fail = 0
    from indepth_analysis.kcif.paths import PDF_DIR
    for rid in ids:
        report = db.get_report_by_id(rid)
        if not report or not report.file_name:
            fail += 1
            continue
        pdf = PDF_DIR / report.file_name
        if not pdf.exists():
            fail += 1
            continue
        if extract_report_md(report, pdf):
            ok += 1
        else:
            fail += 1
    with_img = conn.execute(
        "SELECT COUNT(*) AS n FROM reports WHERE md_path IS NOT NULL").fetchone()["n"]
    logger.info("kcif md backfill: ok=%d fail=%d (md rows=%d)", ok, fail, with_img)
    return {"ok": ok, "fail": fail, "total": len(ids)}
