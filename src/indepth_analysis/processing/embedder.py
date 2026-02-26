import logging
from abc import ABC, abstractmethod

import numpy as np

from indepth_analysis.config import ReferenceConfig

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    """Abstract base class for embedding providers."""

    model_name: str

    @abstractmethod
    def embed(self, text: str) -> bytes:
        """Embed a single text. Returns numpy array as bytes."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> tuple[list[bytes], float]:
        """Embed a batch of texts. Returns (list of embedding bytes, cost in USD)."""
        ...

    @staticmethod
    def to_bytes(arr: np.ndarray) -> bytes:
        return arr.astype(np.float32).tobytes()

    @staticmethod
    def from_bytes(data: bytes, dim: int | None = None) -> np.ndarray:
        arr = np.frombuffer(data, dtype=np.float32)
        return arr


class LocalEmbedder(BaseEmbedder):
    """Local embeddings using sentence-transformers (nomic-embed-text-v2)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading local model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
        return self._model

    def embed(self, text: str) -> bytes:
        arr = self.model.encode([text], normalize_embeddings=True)[0]
        return self.to_bytes(arr)

    def embed_batch(self, texts: list[str]) -> tuple[list[bytes], float]:
        if not texts:
            return [], 0.0
        arrs = self.model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [self.to_bytes(a) for a in arrs], 0.0  # local = free


class GeminiEmbedder(BaseEmbedder):
    """Cloud embeddings using Google Gemini text-embedding-004."""

    # Gemini embedding pricing: free tier is very generous
    # ~$0.00001 per 1000 chars as rough estimate
    COST_PER_1K_CHARS = 0.00001

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import google.generativeai as genai

            genai.configure()  # uses GOOGLE_API_KEY env var
            self._client = genai
        return self._client

    def embed(self, text: str) -> bytes:
        result = self.client.embed_content(
            model=f"models/{self.model_name}",
            content=text,
            task_type="RETRIEVAL_DOCUMENT",
        )
        arr = np.array(result["embedding"], dtype=np.float32)
        arr = arr / np.linalg.norm(arr)
        return self.to_bytes(arr)

    def embed_batch(self, texts: list[str]) -> tuple[list[bytes], float]:
        if not texts:
            return [], 0.0

        results: list[bytes] = []
        total_chars = 0

        # Process in batches of 100 (Gemini limit)
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            total_chars += sum(len(t) for t in batch)

            resp = self.client.embed_content(
                model=f"models/{self.model_name}",
                content=batch,
                task_type="RETRIEVAL_DOCUMENT",
            )
            for emb in resp["embedding"]:
                arr = np.array(emb, dtype=np.float32)
                arr = arr / np.linalg.norm(arr)
                results.append(self.to_bytes(arr))

        cost = (total_chars / 1000) * self.COST_PER_1K_CHARS
        return results, cost


def get_embedder(provider: str, config: ReferenceConfig) -> BaseEmbedder:
    """Factory function to create the appropriate embedder."""
    if provider == "gemini":
        return GeminiEmbedder(config.embedding_model_gemini)
    return LocalEmbedder(config.embedding_model_local)
