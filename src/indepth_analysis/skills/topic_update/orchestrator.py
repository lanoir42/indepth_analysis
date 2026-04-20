"""topic_update 스킬 오케스트레이터.

첫 구현은 dog-fooding — Claude Code 메인 세션이 Agent 도구로 Planner/Generator/
Evaluator + 5 Gatherers를 직접 호출하여 리포트를 생산한다. 본 파일은 향후
CLI 통합 시 `run_topic_update()` 함수 진입점을 제공하기 위한 stub.

향후 구현 방향:
- `claude -p` subprocess 호출로 각 agent 역할 실행
- 아티팩트 파일 경로 규칙 준수
- Planner/Generator/Evaluator 순차 + 5 Gatherers 병렬
- R2 1회 제한, Evaluator gate 자동 판단
- Notion publish 연동 (`indepth_analysis.cli.publish`)
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TopicUpdateSpec:
    """입력 스펙."""

    topic: str
    window_days: int
    cutoff: datetime
    output_dir: Path
    baseline: Path | None = None
    publish_notion: bool = False
    interactive: bool = False


def run_topic_update(spec: TopicUpdateSpec) -> Path:
    """Run the 3-agent pipeline and return FINAL report path.

    Stub — 첫 회차는 Claude Code 메인 세션에서 Agent 도구로 수동 dispatch.
    CLI 등록 시 여기에 `claude -p` subprocess 호출 로직 구현.
    """
    raise NotImplementedError(
        "topic_update CLI 통합은 첫 dog-fooding 실행 이후 작업 예정. "
        "현 시점에는 Claude Code 메인 세션에서 Agent 도구로 각 단계를 dispatch."
    )
