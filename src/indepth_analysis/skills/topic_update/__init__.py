"""topic_update skill — 특정 주제의 최신 업데이트 리포트 생성.

3-agent harness (Planner / Generator / Evaluator), 5 병렬 gatherers (wire /
official / social / kcif / market). Dog-fooding 원칙으로 이 스킬의 첫 실행이
스킬 자체를 증명한다.

Pipeline:
    spec → Planner → 5 Gatherers (parallel) → Generator R1 → Evaluator
    → Generator R2 (if needed, 1 iteration max) → Publisher
"""

from .orchestrator import run_topic_update

__all__ = ["run_topic_update"]
