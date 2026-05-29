#!/usr/bin/env bash
# weekly_euro_macro_brief.sh — 주간 유럽 거시경제 브리프 슬라이드 생성
#
# 사용법:
#   ./scripts/weekly_euro_macro_brief.sh              # 오늘 날짜
#   ./scripts/weekly_euro_macro_brief.sh 2026-05-04   # 특정 날짜
#   ./scripts/weekly_euro_macro_brief.sh --no-publish # 노션 퍼블리시 없이
#
# 소요 시간: 약 10~15분 (3 병렬 에이전트 + 합성 + Evaluator + R2)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"

DATE_ARG="${1:-}"
EXTRA_ARGS="${@:2}"

echo "========================================================"
echo "  유럽 거시경제 주간 브리프 슬라이드"
echo "  날짜: ${DATE_ARG:-$(date +%Y-%m-%d)}"
echo "========================================================"

CMD="uv run indepth report euro-macro-weekly"
[[ -n "$DATE_ARG" ]] && CMD="$CMD --date $DATE_ARG"
CMD="$CMD $EXTRA_ARGS"

echo "실행: $CMD"
eval "$CMD"
