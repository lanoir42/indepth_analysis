#!/usr/bin/env bash
# monthly_euro_macro.sh — 월간 유럽 거시경제 보고서 생성 및 노션 퍼블리시
#
# 사용법:
#   ./scripts/monthly_euro_macro.sh              # 당월 (자동 감지)
#   ./scripts/monthly_euro_macro.sh 2026 5       # 특정 연월
#   ./scripts/monthly_euro_macro.sh 2026 5 --no-web   # WebResearch 건너뜀
#
# 환경 변수 (.env 또는 shell):
#   NOTION_TOKEN, NOTION_PAGE_ID_INDEPTH_ANALYSIS
#
# 소요 시간: 약 15~30분 (WebResearch 10토픽 × Opus 합성 × 부록 LLM 3회)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── 연월 결정 ─────────────────────────────────────────────────────────────
YEAR="${1:-$(date +%Y)}"
MONTH="${2:-$(date +%-m)}"
shift 2 2>/dev/null || true  # 나머지 인수 (예: --no-web) 전달용
EXTRA_ARGS=("$@")

REPORT_MD="reports/euro_macro/${YEAR}-$(printf '%02d' "$MONTH").md"
FINDINGS_JSON="reports/euro_macro/${YEAR}-$(printf '%02d' "$MONTH")-findings.json"

echo "========================================================"
echo "  유럽 거시경제 월간 보고서: ${YEAR}년 ${MONTH}월"
echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"

# ── KCIF 업데이트 확인 ───────────────────────────────────────────────────
echo ""
echo "[1/4] KCIF 데이터베이스 최신화..."
uv run indepth update kcif || echo "  ⚠️  KCIF 업데이트 실패 (기존 데이터로 진행)"

# ── 보고서 생성 ──────────────────────────────────────────────────────────
echo ""
echo "[2/4] 보고서 생성 중 (수집 → 합성 → 부록)..."
echo "  모델: claude-opus-4-20250514"
echo "  WebResearch 토픽: 10개 (동시 4개)"
echo "  예상 소요: 15~30분"
echo ""

uv run indepth report euro-macro \
  --year "$YEAR" \
  --month "$MONTH" \
  "${EXTRA_ARGS[@]}"

if [[ ! -f "$REPORT_MD" ]]; then
  echo "❌ 보고서 생성 실패: $REPORT_MD 없음"
  exit 1
fi

REPORT_SIZE=$(wc -c < "$REPORT_MD")
REPORT_LINES=$(wc -l < "$REPORT_MD")
echo ""
echo "✅ 보고서 생성 완료: $REPORT_MD (${REPORT_LINES}줄 / ${REPORT_SIZE}바이트)"

# ── 노션 퍼블리시 ─────────────────────────────────────────────────────────
echo ""
echo "[3/4] 노션 퍼블리시..."
NOTION_URL=$(uv run indepth publish "$REPORT_MD" --target indepth-analysis 2>&1 | grep "https://" | head -1)

if [[ -z "$NOTION_URL" ]]; then
  echo "⚠️  노션 퍼블리시 결과를 확인하세요"
else
  echo "✅ 노션 퍼블리시 완료: $NOTION_URL"
fi

# ── 완료 요약 ─────────────────────────────────────────────────────────────
echo ""
echo "[4/4] 완료 요약"
echo "  보고서: $REPORT_MD"
echo "  Findings: $FINDINGS_JSON"
[[ -n "$NOTION_URL" ]] && echo "  Notion:  $NOTION_URL"
echo "  완료: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
