"""Tier 4 — Telegram recall agent: read-only semantic search on existing messages."""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.models.issue_track import Evidence
from indepth_analysis.skills.issue_track.agents.base import IssueAgent, IssueRunContext

logger = logging.getLogger(__name__)


def _default_chroma_path() -> Path:
    env = os.environ.get("TELEGRAM_CHROMA_PATH")
    if env:
        return Path(env)
    return Path.home() / "projects" / "telegram" / "chroma_db"


class TelegramRecallAgent(IssueAgent):
    name = "telegram_recall"
    tier = 4

    async def research(self, ctx: IssueRunContext) -> list[Evidence]:
        try:
            import chromadb
            from chromadb import Documents, EmbeddingFunction, Embeddings
            from google import genai as google_genai

            api_key = os.environ.get("GOOGLE_API_KEY", "")

            class _GeminiEmbed(EmbeddingFunction):
                def __call__(self, input: Documents) -> Embeddings:
                    client = google_genai.Client(api_key=api_key)
                    result = client.models.embed_content(
                        model="gemini-embedding-001",
                        contents=list(input),
                    )
                    return [e.values for e in result.embeddings]

            chroma_client = chromadb.PersistentClient(
                path=str(_default_chroma_path())
            )
            # Read-only access to the existing telegram_messages collection
            try:
                collection = chroma_client.get_collection(
                    name="telegram_messages",
                    embedding_function=_GeminiEmbed(),
                )
            except Exception:
                logger.info("telegram_messages collection not found — skipping")
                return []

            query = ctx.topic
            if ctx.seed_keywords:
                query = " ".join(ctx.seed_keywords[:5])

            results = collection.query(
                query_texts=[query],
                n_results=10,
            )

        except ImportError as e:
            logger.warning("ChromaDB/google-genai not available: %s", e)
            return []
        except Exception as e:
            logger.warning("TelegramRecallAgent failed: %s", e)
            return []

        now = datetime.now(UTC).isoformat()
        evidence_list: list[Evidence] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, (doc_id, doc, meta, dist) in enumerate(
            zip(ids, docs, metas, distances)
        ):
            if dist > 0.5:  # Cosine distance > 0.5 means not very similar
                continue
            channel = meta.get("channel_name", meta.get("channel_id", "telegram"))
            date = meta.get("date", "")
            url = f"telegram://{channel}/{doc_id}"
            evidence_list.append(
                Evidence(
                    slug=ctx.slug,
                    tier=self.tier,
                    source_type="telegram_msg",
                    source_name=str(channel),
                    canonical_url=url,
                    title=f"[{channel}] {date[:10] if date else ''}",
                    excerpt=doc[:500] if doc else "",
                    published_at=date[:10] if date else None,
                    fetched_at=now,
                    stance="neutral",
                    credibility_score=None,
                )
            )

        logger.info("TelegramRecallAgent: %d items recalled", len(evidence_list))
        return evidence_list
