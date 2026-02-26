"""Publish markdown reports to Notion as formatted pages."""

import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com"
NOTION_VERSION = "2025-09-03"
BATCH_SIZE = 100

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


class NotionClient:
    """Thin wrapper around the Notion API for page creation and file uploads."""

    def __init__(self, token: str) -> None:
        self._token = token
        self.client = httpx.Client(
            base_url=NOTION_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def create_page(self, parent_id: str, title: str, icon_emoji: str = "📊") -> dict:
        """Create a child page under parent_id and return the page object."""
        payload = {
            "parent": {"page_id": parent_id},
            "icon": {"type": "emoji", "emoji": icon_emoji},
            "properties": {
                "title": [{"text": {"content": title}}],
            },
        }
        resp = self.client.post("/v1/pages", json=payload)
        resp.raise_for_status()
        return resp.json()

    def append_blocks(self, block_id: str, blocks: list[dict]) -> None:
        """Append blocks to a page/block, auto-batching in chunks of 100."""
        for i in range(0, len(blocks), BATCH_SIZE):
            chunk = blocks[i : i + BATCH_SIZE]
            resp = self.client.patch(
                f"/v1/blocks/{block_id}/children",
                json={"children": chunk},
            )
            resp.raise_for_status()

    def upload_file(self, file_path: Path) -> str:
        """Upload a local file via the Notion file upload API.

        Returns the file upload ID to reference in image blocks.
        Two-step process:
        1. Create a file upload object
        2. Send the binary data to /v1/file_uploads/{id}/send
        """
        content_type = _MIME_TYPES.get(
            file_path.suffix.lower(), "application/octet-stream"
        )

        # Step 1: Create file upload object
        resp = self.client.post(
            "/v1/file_uploads",
            json={"filename": file_path.name, "content_type": content_type},
        )
        resp.raise_for_status()
        upload = resp.json()
        upload_id = upload["id"]

        # Step 2: Send binary data via multipart form
        with open(file_path, "rb") as f:
            content = f.read()

        send_resp = httpx.post(
            f"{NOTION_API}/v1/file_uploads/{upload_id}/send",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": NOTION_VERSION,
            },
            files={"file": (file_path.name, content, content_type)},
            timeout=120.0,
        )
        send_resp.raise_for_status()

        return upload_id

    def close(self) -> None:
        self.client.close()


# --- Rich text helpers ---


def _rich_text(content: str, bold: bool = False, link: str | None = None) -> dict:
    """Build a single Notion rich_text element."""
    rt: dict = {
        "type": "text",
        "text": {"content": content},
        "annotations": {
            "bold": bold,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": False,
            "color": "default",
        },
    }
    if link:
        rt["text"]["link"] = {"url": link}
    return rt


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown (bold, links) into rich_text elements."""
    elements: list[dict] = []
    # Pattern: **text**, [text](url), or plain text segments
    pattern = re.compile(
        r"(\*\*(.+?)\*\*)"  # bold
        r"|(\[([^\]]+)\]\(([^)]+)\))"  # link
        r"|([^*\[]+)"  # plain text
    )
    for m in pattern.finditer(text):
        if m.group(1):  # bold
            elements.append(_rich_text(m.group(2), bold=True))
        elif m.group(3):  # link
            url = m.group(5)
            # Notion requires absolute URLs — render anchors/fragments as plain text
            if url.startswith(("http://", "https://")):
                elements.append(_rich_text(m.group(4), link=url))
            else:
                elements.append(_rich_text(m.group(4)))
        elif m.group(6):  # plain
            elements.append(_rich_text(m.group(6)))
    return elements or [_rich_text(text)]


# --- Block builders ---


def _heading_block(level: int, text: str) -> dict:
    """Build a heading block (1, 2, or 3)."""
    rich_text = _parse_inline(text)
    return {
        "type": f"heading_{level}",
        f"heading_{level}": {"rich_text": rich_text},
    }


def _paragraph_block(text: str) -> dict:
    return {
        "type": "paragraph",
        "paragraph": {"rich_text": _parse_inline(text)},
    }


def _quote_block(text: str) -> dict:
    return {
        "type": "quote",
        "quote": {"rich_text": _parse_inline(text)},
    }


def _divider_block() -> dict:
    return {"type": "divider", "divider": {}}


def _image_block_external(url: str, caption: str = "") -> dict:
    block: dict = {
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": url},
        },
    }
    if caption:
        block["image"]["caption"] = [_rich_text(caption)]
    return block


def _image_block_upload(file_upload_id: str, caption: str = "") -> dict:
    block: dict = {
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
        },
    }
    if caption:
        block["image"]["caption"] = [_rich_text(caption)]
    return block


def _table_block(rows: list[list[str]]) -> dict:
    """Build a table block with table_row children."""
    if not rows:
        return _paragraph_block("")
    width = max(len(row) for row in rows)
    table_rows = []
    for row in rows:
        cells = [_parse_inline(cell.strip()) for cell in row]
        # Pad to width
        while len(cells) < width:
            cells.append([_rich_text("")])
        table_rows.append({"type": "table_row", "table_row": {"cells": cells}})
    return {
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": table_rows,
        },
    }


# --- Main parser ---

# Regex patterns
_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_RE_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
_RE_TABLE_ROW = re.compile(r"^\|(.+)\|$")
_RE_TABLE_SEP = re.compile(r"^\|[-:|]+\|$")
_RE_BLOCKQUOTE = re.compile(r"^>\s*(.+)$")
_RE_HR = re.compile(r"^---+$")
_RE_BOLD_KV = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")


def markdown_to_blocks(
    md_text: str,
    upload_map: dict[str, str] | None = None,
) -> list[dict]:
    """Convert markdown text into a list of Notion block dicts.

    Args:
        md_text: The raw markdown string.
        upload_map: Mapping of local image paths to Notion file_upload IDs.
                    If None, local images are skipped.
    """
    upload_map = upload_map or {}
    blocks: list[dict] = []
    lines = md_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if _RE_HR.match(stripped):
            blocks.append(_divider_block())
            i += 1
            continue

        # Heading
        m = _RE_HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            blocks.append(_heading_block(level, m.group(2)))
            i += 1
            continue

        # Image
        m = _RE_IMAGE.match(stripped)
        if m:
            alt_text = m.group(1)
            src = m.group(2)
            if src.startswith(("http://", "https://")):
                blocks.append(_image_block_external(src, alt_text))
            elif src in upload_map:
                blocks.append(_image_block_upload(upload_map[src], alt_text))
            i += 1
            continue

        # Blockquote
        m = _RE_BLOCKQUOTE.match(stripped)
        if m:
            blocks.append(_quote_block(m.group(1)))
            i += 1
            continue

        # Table: collect consecutive table rows
        m = _RE_TABLE_ROW.match(stripped)
        if m:
            table_lines: list[str] = []
            while i < len(lines) and _RE_TABLE_ROW.match(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            # Parse table rows, skip separator lines
            rows: list[list[str]] = []
            for tl in table_lines:
                if _RE_TABLE_SEP.match(tl):
                    continue
                cells = [c.strip() for c in tl.strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append(_table_block(rows))
            continue

        # Bold key-value (e.g., **Price:** $389.00)
        m = _RE_BOLD_KV.match(stripped)
        if m:
            rt = [_rich_text(m.group(1) + ": ", bold=True)]
            rt.extend(_parse_inline(m.group(2)))
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": rt}})
            i += 1
            continue

        # Plain paragraph (may contain inline formatting)
        blocks.append(_paragraph_block(stripped))
        i += 1

    return blocks


_RE_IMAGE_MULTILINE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$", re.MULTILINE)


def _extract_local_images(md_text: str) -> list[str]:
    """Extract local image paths from markdown."""
    paths: list[str] = []
    for m in _RE_IMAGE_MULTILINE.finditer(md_text):
        src = m.group(2)
        if not src.startswith(("http://", "https://")):
            paths.append(src)
    return paths


def publish_to_notion(md_path: Path, token: str, parent_id: str) -> str:
    """Publish a markdown report to Notion as a child page.

    Args:
        md_path: Path to the markdown file.
        token: Notion API integration token.
        parent_id: Notion page ID to create the child page under.

    Returns:
        The URL of the created Notion page.
    """
    md_text = md_path.read_text()
    md_dir = md_path.parent

    # Extract title from first heading
    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    title = title_match.group(1) if title_match else md_path.stem

    client = NotionClient(token)
    try:
        # Upload local chart images
        local_images = _extract_local_images(md_text)
        upload_map: dict[str, str] = {}
        for rel_path in local_images:
            abs_path = md_dir / rel_path
            if abs_path.exists():
                logger.info("Uploading %s", abs_path.name)
                upload_id = client.upload_file(abs_path)
                upload_map[rel_path] = upload_id
                logger.info("Uploaded %s -> %s", abs_path.name, upload_id)
            else:
                logger.warning("Chart file not found: %s", abs_path)

        # Parse markdown into blocks
        blocks = markdown_to_blocks(md_text, upload_map)

        # Create the page
        page = client.create_page(parent_id, title)
        page_id = page["id"]
        page_url = page["url"]

        # Append blocks
        client.append_blocks(page_id, blocks)

        return page_url
    finally:
        client.close()
