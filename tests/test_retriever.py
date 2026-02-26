import numpy as np

from indepth_analysis.models.reference import Chunk
from indepth_analysis.search.indexer import SearchIndex


class TestSearchIndex:
    def _build_index_with_data(self) -> SearchIndex:
        """Create a small test index with known embeddings."""
        index = SearchIndex()

        chunks = [
            Chunk(
                report_id=1,
                chunk_index=0,
                content="European economy analysis",
                token_count=10,
            ),
            Chunk(
                report_id=1,
                chunk_index=1,
                content="ECB interest rate policy",
                token_count=10,
            ),
            Chunk(
                report_id=2,
                chunk_index=0,
                content="Asian market trends",
                token_count=10,
            ),
        ]

        # Create normalized embeddings
        embs = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.7, 0.7, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ],
            dtype=np.float32,
        )
        # Normalize
        embs = embs / np.linalg.norm(embs, axis=1, keepdims=True)

        index.chunks = chunks
        index.report_ids = [c.report_id for c in chunks]
        index.embeddings = embs

        return index

    def test_empty_index(self) -> None:
        index = SearchIndex()
        assert index.size == 0
        assert index.dim == 0
        results = index.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
        assert results == []

    def test_search_basic(self) -> None:
        index = self._build_index_with_data()
        assert index.size == 3

        # Query closest to first chunk
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = index.search(query, top_k=2)
        assert len(results) == 2
        assert results[0][0].content == "European economy analysis"
        assert results[0][1] > results[1][1]  # First has higher score

    def test_search_with_filter(self) -> None:
        index = self._build_index_with_data()

        # Only search in report_id=2
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = index.search(query, top_k=5, report_id_filter={2})
        assert len(results) == 1
        assert results[0][0].report_id == 2

    def test_search_top_k_limit(self) -> None:
        index = self._build_index_with_data()
        query = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        results = index.search(query, top_k=1)
        assert len(results) == 1

    def test_scores_descending(self) -> None:
        index = self._build_index_with_data()
        query = np.array([0.5, 0.5, 0.5, 0.0], dtype=np.float32)
        results = index.search(query, top_k=3)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)
