import logging

import numpy as np

from indepth_analysis.db import ReferenceDB
from indepth_analysis.models.reference import Chunk

logger = logging.getLogger(__name__)


class SearchIndex:
    """In-memory search index built from embedded chunks in the DB."""

    def __init__(self) -> None:
        self.embeddings: np.ndarray | None = None  # (N, dim)
        self.chunks: list[Chunk] = []
        self.report_ids: list[int] = []

    @property
    def size(self) -> int:
        return len(self.chunks)

    @property
    def dim(self) -> int:
        if self.embeddings is not None:
            return self.embeddings.shape[1]
        return 0

    def build(self, db: ReferenceDB) -> None:
        """Load all embedded chunks from the database into memory."""
        rows = db.get_all_embedded_chunks()
        if not rows:
            logger.warning("No embedded chunks found in database")
            return

        self.chunks = []
        self.report_ids = []
        emb_list: list[np.ndarray] = []

        for chunk, emb_bytes in rows:
            arr = np.frombuffer(emb_bytes, dtype=np.float32)
            self.chunks.append(chunk)
            self.report_ids.append(chunk.report_id)
            emb_list.append(arr)

        self.embeddings = np.vstack(emb_list)
        logger.info(
            "Built search index: %d chunks, dim=%d",
            self.size,
            self.dim,
        )

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        report_id_filter: set[int] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Cosine similarity search. Returns (chunk, score) pairs."""
        if self.embeddings is None or self.size == 0:
            return []

        # Normalize query
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)

        # Cosine similarity (embeddings should already be normalized)
        scores = self.embeddings @ query_norm

        # Apply filter if provided
        if report_id_filter is not None:
            mask = np.array(
                [rid in report_id_filter for rid in self.report_ids],
                dtype=bool,
            )
            scores = np.where(mask, scores, -np.inf)

        # Get top-k indices
        k = min(top_k, self.size)
        top_indices = np.argsort(scores)[::-1][:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= -np.inf:
                continue
            results.append((self.chunks[idx], score))

        return results
