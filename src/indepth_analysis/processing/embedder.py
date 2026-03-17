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


def get_embedder(config: ReferenceConfig) -> BaseEmbedder:
    """Factory function to create the local embedder."""
    return LocalEmbedder(config.embedding_model_local)
