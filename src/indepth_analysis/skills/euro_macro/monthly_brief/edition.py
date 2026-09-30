"""회차 설정(edition.json) — 월·단계·기준일·주요 일정을 한 곳에 고정한다.

v2까지는 월별 날짜·사건이 프롬프트에 하드코딩돼 있었다. v3는 모든 단계가
``ROOT/edition.json``에서 회차 정보를 읽는다.

    M=indepth_analysis.skills.euro_macro.monthly_brief.edition
    uv run python -m $M init --month 2026-09 --phase preview \
        --as-of 2026-10-02 --report-date 2026-10-05 \
        --ecb-last 2026-09-10 --ecb-next 2026-10-29
    uv run python -m $M show --month 2026-09
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "3.0.0"
PHASES = ("preview", "interim", "final")
PHASE_TAG = {"preview": "[Preview]", "interim": "[Interim]", "final": "[Final]"}
PHASE_KO = {"preview": "프리뷰", "interim": "중간보고", "final": "종합보고"}
PHASE_BASES = {"interim": "preview", "final": "interim"}
BASE_DIR = Path("reports/euro_macro/monthly_brief")


def _prev_month(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


@dataclass
class Edition:
    month: str
    phase: str
    as_of: str
    report_date: str
    root: str = ""
    collection: str = ""
    window: dict = field(default_factory=dict)
    prior_month_root: str = ""
    ecb: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    phase_bases: dict = field(default_factory=lambda: dict(PHASE_BASES))
    # 초안 기준일(as_of) 이후 보고 전까지 발표될 지표를 '발표 대기 블록'으로 두고,
    # 발표 후 release_patch로 해당 블록만 고친다. 비면 as_of와 같음(대기 없음).
    release_cutoff: str = ""
    version: str = VERSION

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ValueError(f"phase must be one of {PHASES}: {self.phase}")
        self.root = self.root or str(BASE_DIR / self.month)
        self.collection = self.collection or f"EUROPE {self.month.replace('-', '')}"
        self.window = self.window or {"from": f"{self.month}-01", "to": self.as_of}
        self.prior_month_root = self.prior_month_root or str(
            BASE_DIR / _prev_month(self.month)
        )
        self.release_cutoff = self.release_cutoff or self.as_of

    # --- 편의 속성 ---
    @property
    def yyyymm(self) -> str:
        return self.month.replace("-", "")

    @property
    def month_label(self) -> str:
        y, m = self.month.split("-")
        return f"{y}년 {int(m)}월"

    @property
    def has_pending(self) -> bool:
        return self.release_cutoff > self.as_of

    @property
    def pending_window(self) -> dict:
        """발표 대기 구간(as_of 다음 날 ~ release_cutoff)."""
        from datetime import date, timedelta

        start = date.fromisoformat(self.as_of) + timedelta(days=1)
        return {"from": start.isoformat(), "to": self.release_cutoff}

    @property
    def phase_tag(self) -> str:
        return PHASE_TAG[self.phase]

    @property
    def phase_ko(self) -> str:
        return PHASE_KO[self.phase]

    @property
    def base_phase(self) -> str | None:
        return self.phase_bases.get(self.phase)

    def path(self, *parts: str) -> Path:
        return Path(self.root, *parts)

    def doc_name(self, kind: str) -> str:
        """최종 문서 파일명. kind ∈ report|explainer|index."""
        return f"{self.report_date}_europe_macro_{self.phase}_{kind}.md"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    def save(self) -> Path:
        p = self.path("edition.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json() + "\n", encoding="utf-8")
        return p


def load_edition(root_or_month: str | Path) -> Edition:
    """회차 루트 경로 또는 'YYYY-MM'으로 edition.json을 읽는다."""
    s = str(root_or_month)
    root = BASE_DIR / s if len(s) == 7 and s[4] == "-" else Path(s)
    data = json.loads((root / "edition.json").read_text(encoding="utf-8"))
    return Edition(**data)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--month", required=True)
    i.add_argument("--phase", default="preview", choices=PHASES)
    i.add_argument("--as-of", required=True)
    i.add_argument("--report-date", required=True)
    i.add_argument("--root", default="")
    i.add_argument("--ecb-last", default="")
    i.add_argument("--ecb-next", default="")
    i.add_argument("--events", default="", help="events JSON 파일 경로(선택)")
    i.add_argument(
        "--release-cutoff",
        default="",
        help="발표 대기 마감일(초안 as_of 이후 이 날까지 발표분은 대기 블록)",
    )
    s = sub.add_parser("show")
    s.add_argument("--month", required=True)
    a = ap.parse_args()
    if a.cmd == "init":
        root = Path(a.root) if a.root else BASE_DIR / a.month
        existing = root / "edition.json"
        prev: dict = {}
        if existing.exists():  # 단계 전환·기준일 갱신 시 기존 값 보존
            prev = json.loads(existing.read_text(encoding="utf-8"))
        if a.events:
            prev["events"] = json.loads(Path(a.events).read_text(encoding="utf-8"))
        ecb = dict(prev.get("ecb") or {})
        if a.ecb_last:
            ecb["last_meeting"] = a.ecb_last
        if a.ecb_next:
            ecb["next_meeting"] = a.ecb_next
        ed = Edition(
            month=a.month,
            phase=a.phase,
            as_of=a.as_of,
            report_date=a.report_date,
            root=str(root),
            ecb=ecb,
            events=prev.get("events", []),
            release_cutoff=a.release_cutoff or "",
        )
        print(ed.save())
    else:
        print(load_edition(a.month).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
