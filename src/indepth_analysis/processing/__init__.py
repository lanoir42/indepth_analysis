import logging
from pathlib import Path

from rich.console import Console

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.db import ReferenceDB
from indepth_analysis.models.reference import ProcessingStatus, Report
from indepth_analysis.processing.chunker import chunk_text
from indepth_analysis.processing.embedder import get_embedder
from indepth_analysis.processing.pdf_extractor import extract_pdf

logger = logging.getLogger(__name__)


def process_reports(
    reports: list[Report],
    config: ReferenceConfig,
    db: ReferenceDB,
    console: Console,
) -> None:
    """Process reports through extract → chunk → embed pipeline."""
    embedder = get_embedder(config.embedding_provider, config)
    total_cost = 0.0

    for i, report in enumerate(reports, 1):
        assert report.id is not None
        prefix = f"[{i}/{len(reports)}]"

        if not report.file_name:
            logger.warning("%s No file for: %s", prefix, report.title)
            continue

        # Locate the file
        source_row = db.conn.execute(
            "SELECT name FROM sources WHERE id = ?", (report.source_id,)
        ).fetchone()
        source_name = source_row["name"] if source_row else "UNKNOWN"
        filepath = Path(config.download_dir) / source_name / report.file_name

        if not filepath.exists():
            logger.warning("%s File not found: %s", prefix, filepath)
            db.update_report_processing(report.id, status=ProcessingStatus.FAILED)
            continue

        # --- Extract ---
        if report.processing_status == ProcessingStatus.UNPROCESSED:
            with console.status(f"[cyan]{prefix} Extracting: {report.title[:40]}..."):
                try:
                    pages = extract_pdf(filepath)
                    full_text = "\n\n".join(pages)
                except Exception as e:
                    logger.warning("Extraction failed: %s", e)
                    db.update_report_processing(
                        report.id, status=ProcessingStatus.FAILED
                    )
                    continue

                db.update_report_processing(
                    report.id,
                    status=ProcessingStatus.EXTRACTED,
                    page_count=len(pages),
                    extraction_method="pymupdf",
                )
        else:
            # Already extracted, load from chunks or re-extract
            with console.status(
                f"[cyan]{prefix} Re-extracting: {report.title[:40]}..."
            ):
                pages = extract_pdf(filepath)
                full_text = "\n\n".join(pages)

        # --- Chunk ---
        if report.processing_status in (
            ProcessingStatus.UNPROCESSED,
            ProcessingStatus.EXTRACTED,
        ):
            with console.status(f"[cyan]{prefix} Chunking: {report.title[:40]}..."):
                chunks = chunk_text(
                    full_text,
                    pages,
                    report_id=report.id,
                    target_tokens=config.chunk_target_tokens,
                    min_tokens=config.chunk_min_tokens,
                    max_tokens=config.chunk_max_tokens,
                )
                db.insert_chunks(chunks)
                db.update_report_processing(report.id, status=ProcessingStatus.CHUNKED)

        # --- Embed ---
        with console.status(f"[cyan]{prefix} Embedding: {report.title[:40]}..."):
            try:
                chunks_to_embed = db.get_chunks(report_id=report.id)
                texts = [c.content for c in chunks_to_embed]
                embeddings, cost = embedder.embed_batch(texts)

                for chunk, emb in zip(chunks_to_embed, embeddings):
                    chunk.embedding = emb
                    chunk.embedding_model = embedder.model_name

                db.insert_chunks(chunks_to_embed)
                db.update_report_processing(
                    report.id,
                    status=ProcessingStatus.EMBEDDED,
                    embedding_cost_usd=cost,
                )
                total_cost += cost
            except Exception as e:
                logger.warning("Embedding failed: %s", e)
                db.update_report_processing(report.id, status=ProcessingStatus.CHUNKED)
                continue

        console.print(
            f"  [green]{prefix}[/green] {report.title[:60]}"
            f" ({len(chunks_to_embed)} chunks)"
        )

        if config.cost_limit_usd > 0 and total_cost >= config.cost_limit_usd:
            console.print(f"[yellow]Cost limit reached: ${total_cost:.4f}[/yellow]")
            break

    console.print(f"\nProcessed {len(reports)} reports. Total cost: ${total_cost:.4f}")
