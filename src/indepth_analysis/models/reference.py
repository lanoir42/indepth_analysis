from enum import StrEnum

from pydantic import BaseModel, Field


class DownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    SKIPPED = "skipped"
    RESTRICTED = "restricted"


class ProcessingStatus(StrEnum):
    UNPROCESSED = "unprocessed"
    EXTRACTED = "extracted"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    FAILED = "failed"


class Source(BaseModel):
    id: int | None = None
    name: str
    base_url: str
    last_scraped_at: str | None = None
    created_at: str | None = None


class Report(BaseModel):
    id: int | None = None
    source_id: int = 0
    external_id: str
    title: str
    category: str = ""
    author: str = ""
    published_date: str | None = None
    url: str
    file_name: str | None = None
    file_size_bytes: int | None = None
    file_hash: str | None = None
    download_status: DownloadStatus = DownloadStatus.PENDING
    download_error: str | None = None
    processing_status: ProcessingStatus = ProcessingStatus.UNPROCESSED
    page_count: int | None = None
    extraction_method: str | None = None
    extraction_cost_usd: float = 0.0
    embedding_cost_usd: float = 0.0
    created_at: str | None = None


class Chunk(BaseModel):
    id: int | None = None
    report_id: int = 0
    chunk_index: int = 0
    content: str = ""
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    is_table: bool = False
    embedding: bytes | None = Field(default=None, exclude=True)
    embedding_model: str | None = None
