"""프로젝트 루트 앵커 경로 — CWD 무관.

기존 ReferenceConfig는 CWD 상대(``references/references.db``)라 launchd나
다른 디렉토리에서 실행하면 빈 DB가 조용히 새로 생기는 footgun이 있다.
kcif 서브시스템은 전부 이 모듈의 절대경로를 쓴다.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

# src/indepth_analysis/kcif/paths.py → parents[3] = 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parents[3]

REFERENCES_DIR = PROJECT_ROOT / "references"
DB_PATH = REFERENCES_DIR / "references.db"
PDF_DIR = REFERENCES_DIR / "KCIF"
MD_DIR = REFERENCES_DIR / "KCIF_md"          # 추출 텍스트 원본 (저널 스캔 밖)
IMG_DIR = MD_DIR / "img"
TOPIC_DUMP_DIR = MD_DIR / "topics"           # 토픽별 풀 덤프 (롤링 덮어쓰기)
REPORTS_OUT_DIR = PROJECT_ROOT / "reports" / "kcif"  # 저널 스캔 대상
# 주말·휴일로 일간 리포트를 쉬었다는 표지 — `.` 접두 디렉토리라 저널 스캔 밖이다.
# orchestrator 예정 리포트 카드가 이 표지를 보고 그날 KCIF 항목을 뺀다.
SKIP_MARKER_DIR = REPORTS_OUT_DIR / ".skipped"
LOCK_PATH = REFERENCES_DIR / "kcif_daily.lock"
LOG_DIR = Path.home() / "Library" / "Logs"

KST = timezone(timedelta(hours=9))
