"""KCIF agent — searches local KCIF database via semantic search."""

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.db import ReferenceDB
from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.processing.embedder import get_embedder
from indepth_analysis.search.indexer import SearchIndex
from indepth_analysis.skills.base import BaseResearchAgent

logger = logging.getLogger(__name__)

QUERIES = [
    "유럽 경제 전망",
    "ECB 금리 통화정책",
    "유로존 인플레이션 물가",
    "유럽 금융시장 동향",
    "유럽 경기침체 리스크",
    "EU 재정정책",
]


def _build_date_filter(
    db: ReferenceDB, date_from: str, date_to: str
) -> set[int] | None:
    """Return report IDs published within the date range."""
    rows = db.conn.execute(
        "SELECT id FROM reports WHERE published_date >= ? AND published_date <= ?",
        (date_from, date_to),
    ).fetchall()
    if not rows:
        return None
    return {r["id"] for r in rows}


class KCIFAgent(BaseResearchAgent):
    """Searches the local KCIF database using semantic search."""

    name = "KCIF"

    def __init__(self, config: ReferenceConfig) -> None:
        self.config = config

    async def research(self, year: int, month: int) -> AgentResult:
        try:
            return self._search(year, month)
        except Exception as e:
            logger.exception("KCIF agent error")
            return AgentResult(
                agent_name=self.name, search_queries=QUERIES, error=str(e)
            )

    def _search(self, year: int, month: int) -> AgentResult:
        db = ReferenceDB(Path(self.config.db_path))
        index = SearchIndex()
        index.build(db)

        if index.size == 0:
            db.close()
            return AgentResult(
                agent_name=self.name,
                search_queries=QUERIES,
                error="No embedded documents in KCIF database",
            )

        embedder = get_embedder(self.config.embedding_provider, self.config)

        # Date window: target month ± 1 month
        target = date(year, month, 1)
        date_from = (target - timedelta(days=31)).isoformat()
        date_to = (target + timedelta(days=62)).isoformat()
        report_filter = _build_date_filter(db, date_from, date_to)

        findings: list[ResearchFinding] = []
        seen_report_ids: set[int] = set()

        for q in QUERIES:
            query_bytes = embedder.embed(q)
            query_vec = np.frombuffer(query_bytes, dtype=np.float32)
            results = index.search(query_vec, top_k=5, report_id_filter=report_filter)

            for chunk, score in results:
                if chunk.report_id in seen_report_ids:
                    continue
                if score < 0.3:
                    continue

                report = db.get_report_by_id(chunk.report_id)
                if not report:
                    continue

                findings.append(
                    ResearchFinding(
                        title=report.title,
                        summary=chunk.content[:500],
                        source_url=report.url,
                        source_name="KCIF",
                        published_date=report.published_date,
                        relevance_score=round(score, 4),
                    )
                )
                seen_report_ids.add(chunk.report_id)

        db.close()
        return AgentResult(
            agent_name=self.name, findings=findings, search_queries=QUERIES
        )
