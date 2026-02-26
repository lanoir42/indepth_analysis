from indepth_analysis.processing.chunker import (
    _is_table_block,
    chunk_text,
    estimate_tokens,
)


class TestEstimateTokens:
    def test_empty(self) -> None:
        assert estimate_tokens("") == 1  # minimum 1

    def test_short_text(self) -> None:
        tokens = estimate_tokens("Hello world")
        assert tokens >= 1

    def test_korean_text(self) -> None:
        # Korean text has ~3.5 chars per token
        text = "한국은행 금융통화위원회가 기준금리를 동결했습니다."
        tokens = estimate_tokens(text)
        assert tokens > 5


class TestIsTableBlock:
    def test_normal_text(self) -> None:
        assert not _is_table_block("This is normal text.\nWith two lines.")

    def test_tab_separated(self) -> None:
        table = "Header1\tHeader2\tHeader3\nVal1\tVal2\tVal3\nVal4\tVal5\tVal6"
        assert _is_table_block(table)

    def test_pipe_separated(self) -> None:
        table = "Col1 | Col2 | Col3\nA | B | C\nD | E | F"
        assert _is_table_block(table)


class TestChunkText:
    def test_short_text(self) -> None:
        """Short text should produce a single chunk."""
        text = "This is a short text."
        pages = [text]
        chunks = chunk_text(text, pages, report_id=1)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].report_id == 1
        assert chunks[0].chunk_index == 0

    def test_multiple_paragraphs(self) -> None:
        """Multiple short paragraphs should be grouped into chunks."""
        paras = ["Paragraph " + str(i) + ". " * 50 for i in range(10)]
        text = "\n\n".join(paras)
        pages = [text]
        chunks = chunk_text(text, pages, report_id=1)
        assert len(chunks) >= 1
        # All content should be preserved
        total_content = " ".join(c.content for c in chunks)
        for i in range(10):
            assert f"Paragraph {i}" in total_content

    def test_chunk_indices_sequential(self) -> None:
        text = "A. " * 500 + "\n\n" + "B. " * 500 + "\n\n" + "C. " * 500
        pages = [text]
        chunks = chunk_text(text, pages, report_id=1)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_page_tracking(self) -> None:
        page1 = "Content on page one. " * 20
        page2 = "Content on page two. " * 20
        pages = [page1, page2]
        text = "\n\n".join(pages)
        chunks = chunk_text(text, pages, report_id=1)
        assert all(c.page_start is not None for c in chunks)

    def test_empty_text(self) -> None:
        chunks = chunk_text("", [], report_id=1)
        assert len(chunks) == 0
