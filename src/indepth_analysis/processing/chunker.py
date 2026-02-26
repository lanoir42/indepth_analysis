import re

from indepth_analysis.models.reference import Chunk

# Rough token estimate: 1 token ≈ 3.5 chars for Korean, 4 chars for English
CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _is_table_block(text: str) -> bool:
    """Heuristic: check if a block looks like a table."""
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return False
    # Count lines with multiple tab/pipe/space-separated columns
    col_lines = 0
    for line in lines:
        if "\t" in line or "|" in line or len(re.findall(r"\s{3,}", line)) >= 2:
            col_lines += 1
    return col_lines / len(lines) > 0.5


def _find_page(offset: int, page_offsets: list[int]) -> int:
    """Find which page a character offset belongs to (1-indexed)."""
    for i, po in enumerate(page_offsets):
        if offset < po:
            return i  # 0-indexed page
    return len(page_offsets) - 1


def chunk_text(
    full_text: str,
    pages: list[str],
    report_id: int,
    target_tokens: int = 320,
    min_tokens: int = 256,
    max_tokens: int = 384,
) -> list[Chunk]:
    """Split text into semantic chunks respecting paragraph boundaries.

    Tries to split at paragraph boundaries (double newlines), falling back
    to single newlines, then sentence boundaries.
    """
    # Build page offset map for page tracking
    page_offsets: list[int] = []
    offset = 0
    for page in pages:
        offset += len(page) + 2  # +2 for the "\n\n" separator
        page_offsets.append(offset)

    # Split into paragraphs
    paragraphs = re.split(r"\n\s*\n", full_text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[Chunk] = []
    current_text = ""
    current_start_offset = 0
    text_offset = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If this single paragraph exceeds max, split it further
        if para_tokens > max_tokens:
            # Flush current buffer first
            if current_text.strip():
                chunks.append(
                    _make_chunk(
                        current_text.strip(),
                        report_id,
                        len(chunks),
                        current_start_offset,
                        page_offsets,
                    )
                )
                current_text = ""

            # Split large paragraph by sentences
            sub_chunks = _split_large_block(para, max_tokens)
            for sc in sub_chunks:
                chunks.append(
                    _make_chunk(
                        sc,
                        report_id,
                        len(chunks),
                        text_offset,
                        page_offsets,
                    )
                )
            text_offset += len(para) + 2
            current_start_offset = text_offset
            continue

        combined_tokens = estimate_tokens(current_text + "\n\n" + para)

        if combined_tokens > max_tokens and current_text.strip():
            # Flush current chunk
            chunks.append(
                _make_chunk(
                    current_text.strip(),
                    report_id,
                    len(chunks),
                    current_start_offset,
                    page_offsets,
                )
            )
            current_text = para
            current_start_offset = text_offset
        else:
            if current_text:
                current_text += "\n\n" + para
            else:
                current_text = para
                current_start_offset = text_offset

        text_offset += len(para) + 2

    # Flush remaining
    if current_text.strip():
        chunks.append(
            _make_chunk(
                current_text.strip(),
                report_id,
                len(chunks),
                current_start_offset,
                page_offsets,
            )
        )

    # Merge tiny trailing chunks
    if len(chunks) > 1:
        last = chunks[-1]
        if last.token_count and last.token_count < min_tokens:
            prev = chunks[-2]
            merged = prev.content + "\n\n" + last.content
            if estimate_tokens(merged) <= max_tokens * 1.5:
                prev.content = merged
                prev.token_count = estimate_tokens(merged)
                prev.page_end = last.page_end
                chunks.pop()

    return chunks


def _make_chunk(
    text: str,
    report_id: int,
    index: int,
    start_offset: int,
    page_offsets: list[int],
) -> Chunk:
    page_start = _find_page(start_offset, page_offsets) + 1 if page_offsets else None
    page_end = (
        _find_page(start_offset + len(text), page_offsets) + 1 if page_offsets else None
    )
    return Chunk(
        report_id=report_id,
        chunk_index=index,
        content=text,
        page_start=page_start,
        page_end=page_end,
        token_count=estimate_tokens(text),
        is_table=_is_table_block(text),
    )


def _split_large_block(text: str, max_tokens: int) -> list[str]:
    """Split a large block of text by sentence boundaries."""
    # Try sentence splitting
    sentences = re.split(r"(?<=[.!?。])\s+", text)
    if len(sentences) <= 1:
        # Fall back to splitting by newlines
        sentences = text.split("\n")
    if len(sentences) <= 1:
        # Force split by character count
        max_chars = int(max_tokens * CHARS_PER_TOKEN)
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    result: list[str] = []
    current = ""
    for sent in sentences:
        if estimate_tokens(current + " " + sent) > max_tokens and current:
            result.append(current.strip())
            current = sent
        else:
            current = (current + " " + sent).strip() if current else sent
    if current.strip():
        result.append(current.strip())

    return result
