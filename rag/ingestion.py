"""Document ingestion: Docling for PDFs, LlamaIndex readers for Office docs."""

import json
import sys
import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import lancedb

from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.core.llms import MockLLM
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.storage.storage_context import StorageContext
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    LANCEDB_DIR, DEFAULT_OLLAMA_BASE, DEFAULT_EMBED_MODEL,
    CHUNK_SIZE, CHUNK_OVERLAP, DATA_DIR, kb_table_name, mark_kb_indexed,
)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".odt", ".txt", ".md"}

# nomic-embed-text supports up to 8 192 tokens; at ~4 chars/token that is
# ~32 000 chars.  We stay well inside that with a conservative 6 000-char
# ceiling so truncation is only ever triggered by truly pathological chunks
# (e.g. PDFs with base64-encoded blobs or tables with no whitespace).
MAX_EMBED_CHARS = 6_000

# Ollama's default num_ctx for embedding models is 2 048.  We explicitly
# request the full 8 192-token window so normal-sized chunks never hit the
# 400 "input length exceeds content length" error.
EMBED_NUM_CTX = 8_192

# File logger — always writes to data/ingestion.log regardless of UI state
_log_file = DATA_DIR / "ingestion.log"
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("atj.ingestion")
logger.setLevel(logging.DEBUG)
logger.addHandler(_file_handler)
# Also echo to stderr so `python app.py` terminal shows progress
_stderr_handler = logging.StreamHandler()
_stderr_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_stderr_handler)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# Minimum character yield from PyMuPDF before we consider a page "text-bearing"
_PYMUPDF_MIN_CHARS_PER_PAGE = 50


def _extract_pdf_native(path: Path) -> str:
    """
    Use PyMuPDF (fitz) to extract the embedded text layer from a PDF.
    Returns empty string if the PDF has no usable text layer (i.e. it is a scan).
    This is instantaneous and lossless for native-text PDFs.
    """
    import fitz  # PyMuPDF
    doc = fitz.open(str(path))
    pages_text: list[str] = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()
    full_text = "\n".join(pages_text)
    # Heuristic: if the average chars-per-page is below threshold, treat as scan
    avg = len(full_text) / max(len(pages_text), 1)
    return full_text if avg >= _PYMUPDF_MIN_CHARS_PER_PAGE else ""


def _extract_pdf_easyocr(path: Path, log: callable) -> str:
    """
    OCR a scanned PDF using EasyOCR (better accuracy than RapidOCR for legal docs).
    Converts each page to an image then passes it to EasyOCR.
    """
    import fitz
    import easyocr
    import numpy as np

    log("    Using EasyOCR (scanned PDF detected) — this is slower, please wait…")
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    doc = fitz.open(str(path))
    all_text: list[str] = []
    for page_num, page in enumerate(doc, 1):
        # Render at 200 DPI for a good OCR resolution without huge memory use
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
        results = reader.readtext(img, detail=0, paragraph=True)
        page_text = "\n".join(results)
        if page_text.strip():
            all_text.append(f"[Page {page_num}]\n{page_text}")
        else:
            log(f"    ⚠ Page {page_num}: EasyOCR also returned no text.")
    doc.close()
    return "\n\n".join(all_text)


def _extract_pdf_docling(path: Path) -> str:
    """
    Use Docling as the primary structured-extraction path (handles tables,
    headings, multi-column layouts). Falls back gracefully if OCR returns empty.
    """
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(str(path))
    return result.document.export_to_markdown()


def _load_pdf(path: Path, log: callable) -> str:
    """
    Three-stage PDF extraction:
      1. PyMuPDF  — instant; works for any PDF with an embedded text layer.
      2. Docling   — structured extraction with RapidOCR for scans.
      3. EasyOCR  — higher-accuracy OCR fallback when Docling yields nothing.

    Pre-flight: if the file header looks like JSON (CourtListener opinion API
    response saved with a .pdf extension), extract plain_text from it directly.
    """
    import json as _json

    # Pre-flight: detect JSON-disguised-as-PDF (CourtListener API responses)
    try:
        head = path.read_bytes()[:20]
        if head.lstrip()[:1] == b"{":
            raw = _json.loads(path.read_text(encoding="utf-8", errors="replace"))
            text = (raw.get("plain_text") or "").strip()
            if not text:
                # Try HTML fields
                html = (
                    raw.get("html_with_citations")
                    or raw.get("html_lawbox")
                    or raw.get("html")
                    or ""
                ).strip()
                if html:
                    import re as _re
                    text = _re.sub(r"<[^>]+>", " ", html).strip()
            if text:
                log("    ✓ Extracted plain text from CourtListener JSON response.")
                return text
            log("    ⚠ File is a CourtListener JSON response with no usable text.")
            return ""
    except Exception:
        pass  # Not JSON — proceed with normal PDF extraction

    # Stage 1: native text layer
    text = _extract_pdf_native(path)
    if text.strip():
        log(f"    ✓ Native text layer found (PyMuPDF).")
        return text

    # Stage 2: Docling (handles tables/structure; uses RapidOCR internally)
    log("    No native text layer — trying Docling structured extraction…")
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            text = _extract_pdf_docling(path)
        if text.strip():
            log("    ✓ Docling extraction succeeded.")
            return text
        log("    ⚠ Docling returned empty (RapidOCR likely failed).")
    except Exception as exc:
        log(f"    ⚠ Docling error: {exc}")

    # Stage 3: EasyOCR — better accuracy for low-quality / unusual scans
    log("    Falling back to EasyOCR…")
    try:
        text = _extract_pdf_easyocr(path, log)
        if text.strip():
            log("    ✓ EasyOCR extraction succeeded.")
            return text
        log("    ✗ EasyOCR also returned empty — document may be unreadable.")
    except Exception as exc:
        log(f"    ✗ EasyOCR error: {exc}")

    return ""


def _load_office_doc(path: Path) -> str:
    """Extract text from DOCX, XLSX, ODT."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        from docx import Document as DocxDoc
        doc = DocxDoc(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        lines = []
        for sheet in wb.worksheets:
            lines.append(f"# Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                row_text = "\t".join(str(c) if c is not None else "" for c in row)
                if row_text.strip():
                    lines.append(row_text)
        return "\n".join(lines)
    if suffix == ".odt":
        from odf.opendocument import load as odf_load
        from odf.text import P
        from odf import teletype
        doc = odf_load(str(path))
        texts = [teletype.extractText(p) for p in doc.getElementsByType(P)]
        return "\n".join(t for t in texts if t.strip())
    if suffix in {".txt", ".md"}:
        return path.read_text(errors="replace")
    return ""


# ── Delta-indexing helpers ────────────────────────────────────────────────────

def _read_existing_index(db, table_name: str) -> dict[str, tuple[str, list[str]]]:
    """
    Read the existing LanceDB table and return a map:
        { filename: (file_hash, [node_id, ...]) }

    This is used to decide which files are new, changed, or unchanged.
    Returns an empty dict when the table does not exist or cannot be read.
    """
    try:
        if table_name not in db.table_names():
            return {}
        tbl = db.open_table(table_name)
        df = tbl.to_pandas()
        if df.empty:
            return {}

        result: dict[str, tuple[str, list[str]]] = {}
        for _, row in df.iterrows():
            raw = row.get("metadata", {})
            if isinstance(raw, str):
                try:
                    meta = json.loads(raw)
                except Exception:
                    continue
            elif isinstance(raw, dict):
                meta = raw
            else:
                continue

            fname = meta.get("filename")
            fhash = meta.get("file_hash", "")
            node_id = str(row.get("id", ""))
            if fname:
                if fname not in result:
                    result[fname] = (fhash, [])
                result[fname][1].append(node_id)
        return result
    except Exception as exc:
        logger.warning(f"Could not read existing index for delta check: {exc}")
        return {}


def _delete_nodes_for_files(
    db,
    table_name: str,
    filenames: set[str],
    log: Callable[[str], None],
) -> int:
    """
    Delete all LanceDB rows whose metadata.filename is in *filenames*.
    Deletion is done by collecting the node IDs first, then issuing a single
    SQL-style DELETE on the `id` column — which is always a plain string column
    regardless of how metadata is stored (struct vs JSON string).

    Returns the count of rows removed.
    """
    if not filenames or table_name not in db.table_names():
        return 0
    try:
        tbl = db.open_table(table_name)
        df = tbl.to_pandas()
        if df.empty:
            return 0

        ids_to_delete: list[str] = []
        for _, row in df.iterrows():
            raw = row.get("metadata", {})
            if isinstance(raw, str):
                try:
                    meta = json.loads(raw)
                except Exception:
                    continue
            elif isinstance(raw, dict):
                meta = raw
            else:
                continue
            if meta.get("filename") in filenames:
                ids_to_delete.append(str(row.get("id", "")))

        if not ids_to_delete:
            return 0

        id_csv = ", ".join(f"'{i}'" for i in ids_to_delete)
        tbl.delete(f"id IN ({id_csv})")
        log(
            f"   Pruned {len(ids_to_delete)} old vector(s) "
            f"for {len(filenames)} file(s)."
        )
        return len(ids_to_delete)
    except Exception as exc:
        log(f"   ⚠ Could not prune old vectors (will continue): {exc}")
        logger.exception("Vector deletion failed:")
        return 0


# ── Main entry point ──────────────────────────────────────────────────────────

def ingest_folder(
    kb_name: str,
    folder: str,
    embed_model: str = DEFAULT_EMBED_MODEL,
    ollama_base: str = DEFAULT_OLLAMA_BASE,
    progress_cb: Callable[[str], None] | None = None,
    force_full: bool = False,
) -> int:
    """
    Ingest all supported documents in *folder* into a LanceDB table for *kb_name*.

    Delta / incremental mode (default, force_full=False)
    ────────────────────────────────────────────────────
    • Unchanged files (SHA-256 hash identical to stored value) are skipped.
    • Changed files have their old vectors pruned and are re-embedded.
    • New files are embedded and appended to the existing table.
    • Files present in the index but removed from the folder are pruned.
    • If nothing changed the function returns immediately — no embedding work.

    Full rebuild mode (force_full=True)
    ────────────────────────────────────
    Drops the LanceDB table and re-indexes every file from scratch.
    Use this when you switch embedding models or need a guaranteed clean state.

    Returns the total number of documents now indexed in the KB
    (unchanged + newly indexed).
    """
    start_time = time.monotonic()

    def log(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    mode_label = "FULL REBUILD" if force_full else "incremental"
    log(f"=== Ingestion started [{mode_label}]: KB='{kb_name}' folder='{folder}' ===")

    folder_path = Path(folder)
    if not folder_path.exists():
        msg = f"✗ Folder not found: {folder}"
        log(msg)
        raise FileNotFoundError(msg)

    all_files = sorted(
        f for f in folder_path.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not all_files:
        msg = f"✗ No supported documents found in {folder}"
        log(msg)
        raise ValueError(msg)

    log(f"Found {len(all_files)} file(s) in folder.")

    # ── Connect to LanceDB and inspect the existing index ─────────────────────
    db = lancedb.connect(LANCEDB_DIR)
    table_name = kb_table_name(kb_name)

    if force_full:
        try:
            db.drop_table(table_name)
            log(f"Force-full: dropped existing table '{table_name}'.")
        except Exception:
            pass
        existing_index: dict[str, tuple[str, list[str]]] = {}
    else:
        existing_index = _read_existing_index(db, table_name)
        if existing_index:
            log(f"Existing index: {len(existing_index)} document(s) already indexed.")

    # ── Delta analysis ─────────────────────────────────────────────────────────
    # Keys are *relative paths* from the KB folder root (e.g. "exhibits/cover.pdf")
    # rather than bare filenames.  This avoids false cache-hits when two files in
    # different sub-folders share the same name (e.g. motions/cover.pdf and
    # exhibits/cover.pdf would both have been keyed as "cover.pdf" before).
    folder_rel_paths = {
        str(f.relative_to(folder_path)) for f in all_files
    }
    file_hashes = {
        str(f.relative_to(folder_path)): _file_hash(f) for f in all_files
    }

    unchanged_names: set[str] = set()
    changed_files:   list[Path] = []
    new_files:       list[Path] = []

    for fp in all_files:
        rel   = str(fp.relative_to(folder_path))
        fhash = file_hashes[rel]
        if rel in existing_index:
            stored_hash, _ = existing_index[rel]
            if stored_hash == fhash:
                unchanged_names.add(rel)
            else:
                changed_files.append(fp)
        else:
            new_files.append(fp)

    # Files that were previously indexed but are no longer in the folder
    deleted_names: set[str] = {
        rel for rel in existing_index if rel not in folder_rel_paths
    }

    files_to_process = new_files + changed_files

    log(
        f"Delta: {len(new_files)} new  |  {len(changed_files)} changed  |  "
        f"{len(unchanged_names)} unchanged  |  {len(deleted_names)} removed"
    )

    # ── Early exit when nothing has changed ───────────────────────────────────
    if not files_to_process and not deleted_names:
        total_docs = len(unchanged_names)
        log(f"\n✓ Nothing to do — all {total_docs} document(s) are already up to date.")
        mark_kb_indexed(kb_name, total_docs)
        log("=== Ingestion complete (no changes) ===")
        return total_docs

    # ── Prune vectors for changed + deleted files ──────────────────────────────
    to_prune = {str(f.relative_to(folder_path)) for f in changed_files} | deleted_names
    if to_prune:
        log(f"\n── Pruning old vectors for {len(to_prune)} file(s)…")
        _delete_nodes_for_files(db, table_name, to_prune, log)

    if not files_to_process:
        # Only deletions — nothing left to embed
        total_docs = len(unchanged_names)
        log(f"\n✓ Done — pruned {len(deleted_names)} removed file(s). "
            f"{total_docs} document(s) remain in KB.")
        mark_kb_indexed(kb_name, total_docs)
        log("=== Ingestion complete ===")
        return total_docs

    # ── Initialise embedding model ─────────────────────────────────────────────
    log("\nInitialising embedding model…")
    try:
        embedding = OllamaEmbedding(
            model_name=embed_model,
            base_url=ollama_base,
            # Explicitly request the full context window so Ollama doesn't
            # fall back to its default 2 048-token limit and return HTTP 400.
            ollama_additional_kwargs={"options": {"num_ctx": EMBED_NUM_CTX}},
        )
        Settings.embed_model = embedding
        Settings.llm = MockLLM()  # silences "LLM explicitly disabled" warning; never called
    except Exception as exc:
        log(f"✗ Could not initialise embedding model '{embed_model}': {exc}")
        raise

    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    # Choose the LanceDB write mode based on whether the table already exists
    # at this point in execution (i.e. after any pruning has been done):
    #
    #   "overwrite" — table does not exist yet (new KB, or force_full dropped it).
    #                 LanceDB creates the table from scratch.
    #   "append"    — table exists with unchanged vectors still in it; we are
    #                 adding new/updated chunks alongside them.
    #
    # Using "append" on a non-existent table is what caused the
    # "Table … doesn't exist, mode must be 'create' or 'overwrite'" error.
    lancedb_mode = "append" if table_name in db.table_names() else "overwrite"
    log(f"   LanceDB write mode: {lancedb_mode}")

    vector_store = LanceDBVectorStore(
        uri=LANCEDB_DIR, table_name=table_name, mode=lancedb_mode,
    )
    storage_ctx = StorageContext.from_defaults(vector_store=vector_store)

    # ── Phase 1: Extract text ──────────────────────────────────────────────────
    log(f"\n── Phase 1: Extracting text from {len(files_to_process)} file(s)…")
    documents: list[Document] = []
    errors:    list[str]      = []

    for i, file_path in enumerate(files_to_process, 1):
        rel  = str(file_path.relative_to(folder_path))
        tag  = "NEW" if file_path in new_files else "CHANGED"
        pct  = int(i / len(files_to_process) * 100)
        elapsed   = time.monotonic() - start_time
        rate      = i / elapsed if elapsed > 0 else 0
        remaining = (len(files_to_process) - i) / rate if rate > 0 else 0
        eta = f"~{int(remaining)}s remaining" if rate > 0 and remaining > 5 else ""
        log(f"[{i}/{len(files_to_process)} {pct}%] [{tag}] {rel}  {eta}")

        file_start = time.monotonic()
        try:
            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                text = _load_pdf(file_path, log)
            else:
                text = _load_office_doc(file_path)

            file_secs = time.monotonic() - file_start
            if not text.strip():
                msg = f"  ⚠ No text extracted from {rel} — skipping."
                log(msg)
                errors.append(msg)
                continue

            log(f"  ✓ Extracted {len(text.split()):,} words in {file_secs:.1f}s")

            documents.append(Document(
                text=text,
                metadata={
                    "source":    str(file_path),
                    "filename":  rel,            # relative path — unambiguous across sub-folders
                    "kb_name":   kb_name,
                    "file_hash": file_hashes[rel],
                },
            ))
        except Exception as exc:
            file_secs = time.monotonic() - file_start
            msg = f"  ✗ Error on {rel} ({file_secs:.1f}s): {exc}"
            log(msg)
            errors.append(msg)
            logger.exception(f"Full traceback for {rel}:")

    if not documents:
        msg = "✗ No documents could be extracted. Check the log file for details."
        log(msg)
        log(f"Log file: {_log_file}")
        raise ValueError(msg)

    # ── Phase 2: Chunk ─────────────────────────────────────────────────────────
    log(f"\n── Phase 2: Chunking {len(documents)} document(s)…")
    nodes = splitter.get_nodes_from_documents(documents, show_progress=False)
    total_chunks = len(nodes)
    log(f"   {total_chunks} chunks created (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")

    # ── Phase 3: Embed ─────────────────────────────────────────────────────────
    log(f"\n── Phase 3: Embedding {total_chunks} chunks via '{embed_model}'…")
    log("   (progress updates every batch; pace depends on your hardware)")

    EMBED_BATCH   = 8
    embed_start   = time.monotonic()
    embedded_count = 0
    BAR_WIDTH     = 30

    for batch_start in range(0, total_chunks, EMBED_BATCH):
        batch = nodes[batch_start : batch_start + EMBED_BATCH]

        texts = []
        for n in batch:
            raw = n.get_content(metadata_mode="none")
            if len(raw) > MAX_EMBED_CHARS:
                log(f"   ⚠ Chunk too long ({len(raw):,} chars) — truncating to {MAX_EMBED_CHARS:,}.")
                raw = raw[:MAX_EMBED_CHARS]
            texts.append(raw)

        try:
            embeddings = embedding.get_text_embedding_batch(texts, show_progress=False)
        except Exception as exc:
            err_str = str(exc).lower()
            if "400" in str(exc) or "input length" in err_str or "content length" in err_str:
                log(f"   ⚠ Batch {batch_start}–{batch_start+len(batch)} hit Ollama 400: {exc}")
                log(f"   ↳ Retrying individually with {MAX_EMBED_CHARS // 2:,}-char limit…")
                embeddings = []
                for ci, text in enumerate(texts):
                    try:
                        emb = embedding.get_text_embedding(text[:MAX_EMBED_CHARS // 2])
                        embeddings.append(emb)
                    except Exception as e2:
                        log(f"   ✗ Single-chunk embed failed (chunk {batch_start+ci}): {e2}")
                        logger.exception(f"Single-chunk embed failed at {batch_start+ci}:")
                        embeddings.append(None)
            else:
                log(f"   ✗ Embedding error on batch {batch_start}–{batch_start+len(batch)}: {exc}")
                logger.exception("Embedding batch failed:")
                continue

        for node, vec in zip(batch, embeddings):
            if vec is not None:
                node.embedding = vec

        embedded_count += len(batch)
        pct = embedded_count / total_chunks
        filled = int(BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        elapsed_e = time.monotonic() - embed_start
        rate_e    = embedded_count / elapsed_e if elapsed_e > 0 else 0
        eta_e     = int((total_chunks - embedded_count) / rate_e) if rate_e > 0 else 0
        eta_str   = f"  ~{eta_e}s left" if eta_e > 5 else ""
        log(f"   [{bar}] {embedded_count}/{total_chunks} ({pct:.0%}){eta_str}")

    # ── Phase 4: Store ─────────────────────────────────────────────────────────
    log(f"\n── Phase 4: Writing {embedded_count} vectors to LanceDB…")
    store_start = time.monotonic()
    VectorStoreIndex(nodes, storage_context=storage_ctx)
    log(f"   ✓ Stored in {time.monotonic() - store_start:.1f}s")

    total_secs  = time.monotonic() - start_time
    total_docs  = len(unchanged_names) + len(documents)
    mark_kb_indexed(kb_name, total_docs)

    summary = (
        f"\n✓ Done!  {len(documents)} new/updated document(s) indexed"
        f"  ({len(unchanged_names)} unchanged, skipped)."
        f"\n   KB '{kb_name}' now contains {total_docs} document(s)."
        f"\n   Total time: {total_secs:.0f}s ({total_secs/60:.1f} min)."
    )
    if errors:
        summary += f"\n⚠ {len(errors)} file(s) had errors — see details above or in {_log_file}"
    log(summary)
    log("=== Ingestion complete ===")
    return total_docs
