"""Tests for the Notion publisher markdown-to-blocks conversion."""

from indepth_analysis.output.notion_publisher import (
    _extract_local_images,
    markdown_to_blocks,
)


def _text_content(block: dict) -> str:
    """Extract the plain text content from a block's rich_text."""
    btype = block["type"]
    rich_text = block[btype].get("rich_text", [])
    return "".join(rt["text"]["content"] for rt in rich_text)


class TestHeadings:
    def test_h1(self):
        blocks = markdown_to_blocks("# Title")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_1"
        assert _text_content(blocks[0]) == "Title"

    def test_h2(self):
        blocks = markdown_to_blocks("## Section")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_2"
        assert _text_content(blocks[0]) == "Section"

    def test_h3(self):
        blocks = markdown_to_blocks("### Subsection")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_3"
        assert _text_content(blocks[0]) == "Subsection"

    def test_h3_with_link(self):
        blocks = markdown_to_blocks("### [Article Title](https://example.com)")
        assert blocks[0]["type"] == "heading_3"
        rt = blocks[0]["heading_3"]["rich_text"]
        assert rt[0]["text"]["link"]["url"] == "https://example.com"
        assert rt[0]["text"]["content"] == "Article Title"


class TestTables:
    def test_simple_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 1
        table = blocks[0]
        assert table["type"] == "table"
        assert table["table"]["table_width"] == 2
        assert table["table"]["has_column_header"] is True
        # Header + 2 data rows = 3 rows (separator skipped)
        rows = table["table"]["children"]
        assert len(rows) == 3

    def test_table_with_alignment(self):
        md = "| Metric | Value |\n|--------|------:|\n| P/E | 24.33 |"
        blocks = markdown_to_blocks(md)
        table = blocks[0]
        rows = table["table"]["children"]
        assert len(rows) == 2  # header + 1 data row


class TestImages:
    def test_external_image(self):
        blocks = markdown_to_blocks("![thumb](https://example.com/img.png)")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"
        img = blocks[0]["image"]
        assert img["type"] == "external"
        assert img["external"]["url"] == "https://example.com/img.png"
        assert img["caption"][0]["text"]["content"] == "thumb"

    def test_local_image_with_upload(self):
        upload_map = {"charts/MSFT_price.png": "upload-id-123"}
        blocks = markdown_to_blocks(
            "![Price](charts/MSFT_price.png)", upload_map=upload_map
        )
        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"
        img = blocks[0]["image"]
        assert img["type"] == "file_upload"
        assert img["file_upload"]["id"] == "upload-id-123"

    def test_local_image_without_upload_skipped(self):
        blocks = markdown_to_blocks("![Price](charts/MSFT_price.png)")
        assert len(blocks) == 0

    def test_external_image_no_caption(self):
        blocks = markdown_to_blocks("![](https://example.com/img.png)")
        img = blocks[0]["image"]
        assert img["type"] == "external"
        # Empty alt text means no caption
        assert "caption" not in img or img["caption"][0]["text"]["content"] == ""


class TestBlockquotes:
    def test_blockquote(self):
        blocks = markdown_to_blocks("> Some quoted text")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "quote"
        assert _text_content(blocks[0]) == "Some quoted text"


class TestDividers:
    def test_hr(self):
        blocks = markdown_to_blocks("---")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_long_hr(self):
        blocks = markdown_to_blocks("------")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"


class TestBoldKeyValue:
    def test_bold_kv(self):
        blocks = markdown_to_blocks("**Price:** $389.00")
        assert len(blocks) == 1
        rt = blocks[0]["paragraph"]["rich_text"]
        assert rt[0]["text"]["content"] == "Price: "
        assert rt[0]["annotations"]["bold"] is True
        assert rt[1]["text"]["content"] == "$389.00"
        assert rt[1]["annotations"]["bold"] is False


class TestParagraphs:
    def test_plain_text(self):
        blocks = markdown_to_blocks("Just some text")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        assert _text_content(blocks[0]) == "Just some text"

    def test_empty_lines_skipped(self):
        blocks = markdown_to_blocks("Line 1\n\n\nLine 2")
        assert len(blocks) == 2
        assert _text_content(blocks[0]) == "Line 1"
        assert _text_content(blocks[1]) == "Line 2"


class TestInlineParsing:
    def test_bold_in_paragraph(self):
        blocks = markdown_to_blocks("This is **bold** text")
        rt = blocks[0]["paragraph"]["rich_text"]
        assert any(
            el["annotations"]["bold"] and el["text"]["content"] == "bold" for el in rt
        )

    def test_link_in_paragraph(self):
        blocks = markdown_to_blocks("Visit [site](https://example.com) now")
        rt = blocks[0]["paragraph"]["rich_text"]
        link_el = [el for el in rt if el["text"].get("link")]
        assert len(link_el) == 1
        assert link_el[0]["text"]["link"]["url"] == "https://example.com"


class TestExtractLocalImages:
    def test_finds_local_paths(self):
        md = (
            "![a](charts/price.png)\n"
            "![b](https://example.com/img.png)\n"
            "![c](charts/rsi.png)"
        )
        paths = _extract_local_images(md)
        assert paths == ["charts/price.png", "charts/rsi.png"]

    def test_empty_on_no_images(self):
        assert _extract_local_images("No images here") == []


class TestBatching:
    def test_large_document_produces_many_blocks(self):
        """Verify that a large markdown produces >100 blocks for batching."""
        lines = [f"## Heading {i}" for i in range(120)]
        md = "\n\n".join(lines)
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 120

    def test_batch_chunks(self):
        """Verify NotionClient.append_blocks would split into chunks."""
        from unittest.mock import MagicMock

        from indepth_analysis.output.notion_publisher import BATCH_SIZE, NotionClient

        client = NotionClient.__new__(NotionClient)
        client.client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        client.client.patch.return_value = mock_resp

        blocks = [{"type": "divider", "divider": {}} for _ in range(250)]
        client.append_blocks("page-id", blocks)

        assert client.client.patch.call_count == 3
        # First chunk: 100, second: 100, third: 50
        calls = client.client.patch.call_args_list
        assert len(calls[0][1]["json"]["children"]) == BATCH_SIZE
        assert len(calls[1][1]["json"]["children"]) == BATCH_SIZE
        assert len(calls[2][1]["json"]["children"]) == 50


class TestFullReport:
    def test_report_structure(self):
        """Test that a realistic report snippet produces expected block types."""
        md = """# Investment Analysis: MSFT

**Price:** $389.00
**Date:** 2026-02-25

## Technical Analysis

| Metric | Value |
|--------|------:|
| P/E | 24.33 |
| RSI | 31.50 |

![Price Chart](charts/MSFT_price.png)

## Recent News

### [Article Title](https://example.com/article)

![thumbnail](https://example.com/thumb.jpg)

**Yahoo Finance** | 2026-02-25

> MSFT: NEUTRAL. Some summary text.
"""
        upload_map = {"charts/MSFT_price.png": "upload-123"}
        blocks = markdown_to_blocks(md, upload_map=upload_map)

        types = [b["type"] for b in blocks]
        assert "heading_1" in types
        assert "heading_2" in types
        assert "heading_3" in types
        assert "table" in types
        assert "image" in types
        assert "quote" in types
        assert types.count("image") == 2  # 1 uploaded + 1 external
