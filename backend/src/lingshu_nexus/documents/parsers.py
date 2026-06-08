"""DocumentParser adapters for deterministic Markdown and baseline PDF parsing."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from typing import Any, Protocol

from lingshu_domain import ChunkLocator, SourceChunk
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.documents.models import ParsedDocument

MARKDOWN_PARSER_VERSION = "markdown-deterministic-v0.1.0"
PDF_PARSER_VERSION = "pypdf-baseline-v0.1.0"


class DocumentParseError(ValueError):
    """Raised when a supported parser cannot produce reliable chunks."""


class UnsupportedDocumentTypeError(ValueError):
    """Raised when no parser is configured for the upload."""


@dataclass(frozen=True)
class DocumentParseRequest:
    domain_id: str
    document_id: str
    filename: str
    content: bytes
    media_type: str
    title_hint: str | None = None

    def __post_init__(self) -> None:
        require_domain_id(self.domain_id)
        require_text(self.document_id, "DocumentParseRequest.document_id")
        require_text(self.filename, "DocumentParseRequest.filename")
        require_text(self.media_type, "DocumentParseRequest.media_type")


class DocumentParser(Protocol):
    def parse(self, request: DocumentParseRequest) -> ParsedDocument:
        """Parse bytes into source chunks with stable locators."""


class MarkdownDocumentParser:
    parser_version = MARKDOWN_PARSER_VERSION

    def parse(self, request: DocumentParseRequest) -> ParsedDocument:
        text = _decode_markdown(request.content)
        paragraphs = _markdown_paragraphs(text)
        title = request.title_hint or _markdown_title(text) or _title_from_filename(request.filename)
        chunks: list[SourceChunk] = []
        for chunk_index, paragraph in enumerate(paragraphs):
            chunks.append(
                SourceChunk(
                    id=_chunk_id(request.document_id, chunk_index),
                    domain_id=request.domain_id,
                    document_id=request.document_id,
                    locator=ChunkLocator(
                        chunk_index=chunk_index,
                        heading=paragraph.heading,
                        paragraph=paragraph.paragraph_index,
                    ),
                    text=paragraph.text,
                    parser_version=self.parser_version,
                )
            )
        if not chunks:
            raise DocumentParseError("Markdown parser found no non-empty paragraphs")
        return ParsedDocument(title=title, chunks=tuple(chunks), parser_version=self.parser_version)


class PyPdfDocumentParser:
    parser_version = PDF_PARSER_VERSION

    def parse(self, request: DocumentParseRequest) -> ParsedDocument:
        if not request.content.startswith(b"%PDF"):
            raise DocumentParseError("PDF parser could not read file: missing PDF header")
        pdf_reader_class: Any
        try:
            from pypdf import PdfReader as PypdfReader

            pdf_reader_class = PypdfReader
        except ImportError as exc:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyPDF2")
                    pdf_reader_class = getattr(import_module("PyPDF2"), "PdfReader")
            except ImportError:
                return self._parse_with_minimal_fallback(request, exc)

        try:
            reader = pdf_reader_class(BytesIO(request.content))
        except Exception as exc:  # pragma: no cover - exact parser exceptions vary
            raise DocumentParseError(f"PDF parser could not read file: {exc}") from exc

        chunks: list[SourceChunk] = []
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover - exact parser exceptions vary
                raise DocumentParseError(f"PDF parser failed on page {page_index}: {exc}") from exc
            for paragraph_index, text in enumerate(_plain_text_paragraphs(page_text), start=1):
                chunk_index = len(chunks)
                chunks.append(
                    SourceChunk(
                        id=_chunk_id(request.document_id, chunk_index),
                        domain_id=request.domain_id,
                        document_id=request.document_id,
                        locator=ChunkLocator(
                            chunk_index=chunk_index,
                            page=page_index,
                            paragraph=paragraph_index,
                        ),
                        text=text,
                        parser_version=self.parser_version,
                    )
                )
        if not chunks:
            raise DocumentParseError("PDF parser extracted no text chunks")
        metadata_title = reader.metadata.title if reader.metadata is not None else None
        title = request.title_hint or metadata_title or _title_from_filename(request.filename)
        return ParsedDocument(title=title, chunks=tuple(chunks), parser_version=self.parser_version)

    def _parse_with_minimal_fallback(
        self, request: DocumentParseRequest, import_error: ImportError
    ) -> ParsedDocument:
        page_texts = _fallback_pdf_text_pages(request.content)
        chunks: list[SourceChunk] = []
        for page_index, page_text in enumerate(page_texts, start=1):
            for paragraph_index, text in enumerate(_plain_text_paragraphs(page_text), start=1):
                chunk_index = len(chunks)
                chunks.append(
                    SourceChunk(
                        id=_chunk_id(request.document_id, chunk_index),
                        domain_id=request.domain_id,
                        document_id=request.document_id,
                        locator=ChunkLocator(
                            chunk_index=chunk_index,
                            page=page_index,
                            paragraph=paragraph_index,
                        ),
                        text=text,
                        parser_version=self.parser_version,
                    )
                )
        if not chunks:
            raise DocumentParseError("PyPDF2 is not installed and fallback extracted no text") from (
                import_error
            )
        title = request.title_hint or _title_from_filename(request.filename)
        return ParsedDocument(title=title, chunks=tuple(chunks), parser_version=self.parser_version)


class CompositeDocumentParser:
    def __init__(
        self,
        *,
        markdown_parser: DocumentParser,
        pdf_parser: DocumentParser,
    ) -> None:
        self._markdown_parser = markdown_parser
        self._pdf_parser = pdf_parser

    def parse(self, request: DocumentParseRequest) -> ParsedDocument:
        document_type = detect_document_type(request.filename, request.media_type)
        if document_type == "markdown":
            return self._markdown_parser.parse(request)
        if document_type == "pdf":
            return self._pdf_parser.parse(request)
        raise UnsupportedDocumentTypeError(
            f"Unsupported document type for {request.filename} ({request.media_type})"
        )


@dataclass(frozen=True)
class _MarkdownParagraph:
    heading: str | None
    paragraph_index: int
    text: str


def detect_document_type(filename: str, media_type: str | None) -> str | None:
    lower_filename = filename.lower()
    normalized_media_type = (media_type or "").split(";", maxsplit=1)[0].strip().lower()
    if lower_filename.endswith((".md", ".markdown")):
        return "markdown"
    if lower_filename.endswith(".pdf"):
        return "pdf"
    if normalized_media_type in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if normalized_media_type == "application/pdf":
        return "pdf"
    return None


def canonical_media_type(filename: str, media_type: str | None) -> str | None:
    document_type = detect_document_type(filename, media_type)
    if document_type == "markdown":
        return "text/markdown"
    if document_type == "pdf":
        return "application/pdf"
    normalized_media_type = (media_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized_media_type:
        return normalized_media_type
    return None


def _decode_markdown(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("Markdown content must be UTF-8") from exc


def _markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def _markdown_paragraphs(text: str) -> tuple[_MarkdownParagraph, ...]:
    paragraphs: list[_MarkdownParagraph] = []
    current_heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        paragraph_text = " ".join(part.strip() for part in buffer if part.strip())
        buffer.clear()
        if paragraph_text:
            paragraphs.append(
                _MarkdownParagraph(
                    heading=current_heading,
                    paragraph_index=len(paragraphs) + 1,
                    text=paragraph_text,
                )
            )

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            current_heading = stripped.lstrip("#").strip() or None
            continue
        buffer.append(stripped)
    flush()
    return tuple(paragraphs)


def _plain_text_paragraphs(text: str) -> tuple[str, ...]:
    normalized_lines = [line.strip() for line in text.replace("\r\n", "\n").splitlines()]
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        paragraph_text = " ".join(buffer).strip()
        buffer.clear()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    for line in normalized_lines:
        if not line:
            flush()
            continue
        buffer.append(line)
    flush()
    return tuple(paragraphs)


def _fallback_pdf_text_pages(content: bytes) -> tuple[str, ...]:
    if not content.startswith(b"%PDF"):
        raise DocumentParseError("PDF parser could not read file: missing PDF header")
    pages: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", content, flags=re.DOTALL):
        stream_text = match.group(1).decode("latin-1", errors="ignore")
        literals = [_unescape_pdf_literal(value) for value in _pdf_text_literals(stream_text)]
        page_text = "\n".join(value for value in literals if value.strip())
        if page_text.strip():
            pages.append(page_text)
    if not pages:
        raise DocumentParseError("PDF parser extracted no text chunks")
    return tuple(pages)


def _pdf_text_literals(stream_text: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in re.finditer(r"\(((?:\\.|[^\\)])*)\)\s*Tj", stream_text):
        values.append(match.group(1))
    return tuple(values)


def _unescape_pdf_literal(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def _title_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", maxsplit=1)[-1].rsplit(".", maxsplit=1)[0]
    return stem.strip() or "untitled"


def _chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}_chunk_{chunk_index:04d}"
