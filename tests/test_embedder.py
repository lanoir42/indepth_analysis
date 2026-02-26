import numpy as np

from indepth_analysis.processing.embedder import BaseEmbedder


class TestBaseEmbedderHelpers:
    def test_to_and_from_bytes_roundtrip(self) -> None:
        arr = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        data = BaseEmbedder.to_bytes(arr)
        restored = BaseEmbedder.from_bytes(data)
        np.testing.assert_array_almost_equal(arr, restored)

    def test_to_bytes_dtype_conversion(self) -> None:
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        data = BaseEmbedder.to_bytes(arr)
        restored = BaseEmbedder.from_bytes(data)
        assert restored.dtype == np.float32
        np.testing.assert_array_almost_equal(arr.astype(np.float32), restored)

    def test_empty_array(self) -> None:
        arr = np.array([], dtype=np.float32)
        data = BaseEmbedder.to_bytes(arr)
        restored = BaseEmbedder.from_bytes(data)
        assert len(restored) == 0
