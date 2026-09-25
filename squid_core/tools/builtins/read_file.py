"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

import hashlib
import math
from pathlib import Path
from typing import Any, Callable, Sequence

from squid_core.image_content import (
    MAX_IMAGE_BYTES,
    SUPPORTED_IMAGE_SUFFIXES,
    UNSUPPORTED_IMAGE_SUFFIXES,
    ImageValidationError,
    inspect_image_bytes,
)
from squid_core.settings import ReadFileSettings

TOOL_NAME = "read_file"
DEFAULT_SETTINGS = ReadFileSettings()
MAX_REQUESTED_RANGES = 8
MAX_REQUESTED_PAGE_RANGES = 8
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES_PER_READ = 20
MAX_PDF_RENDER_PIXELS = 40_000_000
PDF_RENDER_SCALE = 2.0

GeneratedImageStore = Callable[
    [str, str, str, Callable[[], bytes], str | None],
    tuple[str, bool],
]


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Read a UTF-8 text file, PDF, or supported PNG, JPG/JPEG, or WebP "
                "image at an absolute path. For PDFs, use pages for 1-based inclusive "
                "page ranges; the selected pages are text-extracted and lazily rendered "
                "to session PNG files. Image reads do not accept ranges. Use ranges for "
                "one or several "
                "known relevant 1-based inclusive regions of the same file, combining "
                "regions needed for the same decision. Omit ranges only when file-wide "
                "context is needed; full-file reads return at most "
                f"{DEFAULT_SETTINGS.default_max_lines} lines. Small ranges may include "
                "surrounding context, and total normalized coverage must stay within the "
                f"{DEFAULT_SETTINGS.default_max_lines}-line limit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "ranges": {
                        "type": "array",
                        "description": (
                            "Optional targeted 1-based inclusive regions in this file"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                            },
                            "required": ["start_line", "end_line"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                        "maxItems": MAX_REQUESTED_RANGES,
                    },
                    "pages": {
                        "type": "array",
                        "description": (
                            "Optional targeted 1-based inclusive PDF page ranges. "
                            "Valid only for PDF files; omit to read all pages when the "
                            f"document has at most {MAX_PDF_PAGES_PER_READ} pages."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_page": {"type": "integer"},
                                "end_page": {"type": "integer"},
                            },
                            "required": ["start_page", "end_page"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                        "maxItems": MAX_REQUESTED_PAGE_RANGES,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }


# Read a file and return the result in a consistent shape.
def execute(
    _repo_root: Path,
    path: str,
    ranges: list[dict[str, int]] | None = None,
    pages: list[dict[str, int]] | None = None,
    *,
    settings: ReadFileSettings = DEFAULT_SETTINGS,
    snapshot_asset: Callable[[bytes, str], str] | None = None,
    ensure_generated_image: GeneratedImageStore | None = None,
) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "read_file requires an absolute path",
        }

    range_error = _validate_read_ranges(ranges)
    if range_error is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": range_error,
        }

    page_error = _validate_page_ranges(pages)
    if page_error is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": page_error,
        }

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(file_path, path, ranges, pages, ensure_generated_image)
    if pages is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "page ranges are supported only for PDF files",
        }
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _read_image(file_path, path, ranges, snapshot_asset)
    if suffix in UNSUPPORTED_IMAGE_SUFFIXES:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": f"unsupported image extension: {file_path.suffix.lower()}",
        }

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if ranges is not None:
        return _read_ranges(
            path,
            lines,
            total_lines,
            ranges,
            settings,
        )

    actual_start = 1
    actual_end = total_lines
    original_chars = len(content)
    if total_lines <= settings.default_max_lines:
        content_metadata = {
            "truncated": False,
            "original_chars": original_chars,
            "returned_chars": original_chars,
        }
    else:
        # Keep both ends symmetrical so the omitted interval is easy to
        # inspect with a follow-up ranged read.
        head_lines = settings.default_max_lines // 2
        tail_lines = settings.default_max_lines - head_lines
        tail_start = total_lines - tail_lines + 1
        returned_ranges = [(1, head_lines), (tail_start, total_lines)]
        content = _render_ranges(lines, returned_ranges)
        content_metadata = {
            "truncated": True,
            "original_chars": original_chars,
            "returned_chars": len(content),
        }

    result = {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
        "content_truncated": content_metadata["truncated"],
        "content_original_chars": content_metadata["original_chars"],
        "content_returned_chars": content_metadata["returned_chars"],
        "start_line": actual_start,
        "end_line": actual_end,
        "total_lines": total_lines,
        "ranged": False,
    }
    if content_metadata["truncated"]:
        result["returned_line_ranges"] = _range_dicts(returned_ranges)
        result["truncation_guidance"] = (
            f"Full-file read truncated to {settings.default_max_lines} of {total_lines} lines; "
            f"returned lines 1-{head_lines} and {tail_start}-{total_lines}. Use "
            "ranges to inspect the missing relevant section."
        )
    return result


def _read_pdf(
    file_path: Path,
    path: str,
    ranges: list[dict[str, int]] | None,
    pages: list[dict[str, int]] | None,
    ensure_generated_image: GeneratedImageStore | None,
) -> dict:
    """Extract and lazily render only the selected pages of one PDF."""

    if ranges is not None:
        return _pdf_error(path, "line ranges are not supported for PDF files; use pages")
    if ensure_generated_image is None:
        return _pdf_error(path, "PDF reads require active session asset storage")

    try:
        size_bytes = file_path.stat().st_size
        if size_bytes > MAX_PDF_BYTES:
            return _pdf_error(
                path,
                f"PDF is {size_bytes} bytes; maximum supported size is {MAX_PDF_BYTES} bytes",
            )
        pdf_data = file_path.read_bytes()
        if len(pdf_data) > MAX_PDF_BYTES:
            return _pdf_error(
                path,
                f"PDF is {len(pdf_data)} bytes; maximum supported size is "
                f"{MAX_PDF_BYTES} bytes",
            )
        import pymupdf

        document = pymupdf.open(stream=pdf_data, filetype="pdf")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        return _pdf_error(path, f"invalid or unreadable PDF: {error}")

    try:
        if document.needs_pass:
            return _pdf_error(path, "encrypted PDFs are not supported")
        total_pages = document.page_count
        selected_ranges, selection_error = _selected_pdf_ranges(pages, total_pages)
        if selection_error is not None:
            return _pdf_error(path, selection_error)

        source_digest = hashlib.sha256(pdf_data).hexdigest()
        folder_name = f"{file_path.stem} rendered images"
        folder_identity = f"pdf-sha256={source_digest}"
        rendered_pages = []
        text_parts = []
        for start_page, end_page in selected_ranges:
            for page_number in range(start_page, end_page + 1):
                page = document.load_page(page_number - 1)
                extracted = page.get_text("text")
                text_parts.append(f"<<< PDF PAGE {page_number} >>>\n")
                text_parts.append(
                    extracted if extracted.strip() else "[no extractable text on this page]\n"
                )
                if extracted and not extracted.endswith("\n"):
                    text_parts.append("\n")

                filename = f"page-{page_number}.png"
                cache_key = (
                    f"pdf-sha256={source_digest};page={page_number};"
                    f"renderer={pymupdf.VersionBind};scale={PDF_RENDER_SCALE};"
                    f"max-pixels={MAX_PDF_RENDER_PIXELS}"
                )
                rendered_path, reused = ensure_generated_image(
                    folder_name,
                    filename,
                    cache_key,
                    lambda page=page: _render_pdf_page(page, pymupdf),
                    folder_identity,
                )
                rendered_pages.append(
                    {
                        "page": page_number,
                        "path": rendered_path,
                        "reused": reused,
                    }
                )
    except (OSError, RuntimeError, ValueError) as error:
        return _pdf_error(path, f"could not read or render PDF: {error}")
    finally:
        document.close()

    content = "".join(text_parts)
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "media_type": "pdf",
        "content": content,
        "content_truncated": False,
        "content_original_chars": len(content),
        "content_returned_chars": len(content),
        "total_pages": total_pages,
        "returned_page_ranges": [
            {"start_page": start, "end_page": end}
            for start, end in selected_ranges
        ],
        "rendered_pages": rendered_pages,
    }


def _render_pdf_page(page, pymupdf_module) -> bytes:
    """Render a PDF page within the same pixel ceiling used for image ingest."""

    page_pixels = page.rect.width * page.rect.height
    if page_pixels <= 0:
        raise ValueError("PDF page dimensions must be positive")
    scale = min(
        PDF_RENDER_SCALE,
        math.sqrt(MAX_PDF_RENDER_PIXELS / page_pixels),
    )
    pixmap = page.get_pixmap(
        matrix=pymupdf_module.Matrix(scale, scale),
        alpha=False,
    )
    if pixmap.width * pixmap.height > MAX_PDF_RENDER_PIXELS:
        raise ValueError(
            "rendered PDF page exceeds the maximum supported pixel count"
        )
    return pixmap.tobytes("png")


def _selected_pdf_ranges(
    requested: list[dict[str, int]] | None,
    total_pages: int,
) -> tuple[list[tuple[int, int]], str | None]:
    """Normalize PDF page selection without applying text-line expansion rules."""

    if total_pages < 1:
        return [], "PDF contains no pages"
    if requested is None:
        if total_pages > MAX_PDF_PAGES_PER_READ:
            return [], (
                f"PDF has {total_pages} pages; request pages explicitly with at most "
                f"{MAX_PDF_PAGES_PER_READ} pages per read"
            )
        return [(1, total_pages)], None

    normalized = []
    for item in requested:
        if item["start_page"] > total_pages:
            return [], (
                f"start_page {item['start_page']} exceeds PDF page count {total_pages}"
            )
        normalized.append(
            (item["start_page"], min(item["end_page"], total_pages))
        )
    merged = _merge_ranges(normalized)
    selected_count = sum(end - start + 1 for start, end in merged)
    if selected_count > MAX_PDF_PAGES_PER_READ:
        return [], (
            f"requested PDF read covers {selected_count} pages; maximum is "
            f"{MAX_PDF_PAGES_PER_READ} pages"
        )
    return merged, None


def _pdf_error(path: str, error: str) -> dict:
    return {"ok": False, "tool": TOOL_NAME, "path": path, "error": error}


def _read_image(
    file_path: Path,
    path: str,
    ranges: list[dict[str, int]] | None,
    snapshot_asset: Callable[[bytes, str], str] | None,
) -> dict:
    """Validate and snapshot an image while preserving its exact source bytes."""

    if ranges is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "line ranges are not supported for image files",
        }
    if snapshot_asset is None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "image reads require active session asset storage",
        }

    try:
        size_bytes = file_path.stat().st_size
        if size_bytes > MAX_IMAGE_BYTES:
            raise ImageValidationError(
                f"image is {size_bytes} bytes; maximum supported size is "
                f"{MAX_IMAGE_BYTES} bytes"
            )
        data = file_path.read_bytes()
        metadata = inspect_image_bytes(data, file_path.suffix)
    except (ImageValidationError, OSError) as error:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": str(error),
        }

    digest = hashlib.sha256(data).hexdigest()
    try:
        asset_id = snapshot_asset(data, metadata["canonical_extension"])
        expected_asset_id = f"{digest}{metadata['canonical_extension']}"
        if asset_id != expected_asset_id:
            raise OSError(
                "session asset storage returned an unexpected content identifier"
            )
    except Exception as error:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": f"could not snapshot image into the session: {error}",
        }

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "media_type": "image",
        "image": {
            "version": 1,
            "asset_id": asset_id,
            "sha256": digest,
            "mime_type": metadata["mime_type"],
            "format": metadata["format"],
            "width": metadata["width"],
            "height": metadata["height"],
            "size_bytes": metadata["size_bytes"],
        },
    }


def _read_ranges(
    path: str,
    lines: list[str],
    total_lines: int,
    ranges: list[dict[str, int]],
    settings: ReadFileSettings,
) -> dict:
    """Return normalized targeted regions through the public range-list contract."""

    normalized = []
    for requested in ranges:
        start_line = requested["start_line"]
        end_line = min(requested["end_line"], total_lines)
        if start_line > total_lines:
            continue
        normalized.append(
            _expanded_range(
                start_line,
                end_line,
                total_lines,
                settings.minimum_range_lines,
            )
        )

    merged = _merge_ranges(normalized)
    source_lines = sum(end - start + 1 for start, end in merged)
    if source_lines > settings.default_max_lines:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": (
                "targeted read covers "
                f"{source_lines} lines after normalization; maximum total coverage is "
                f"{settings.default_max_lines} lines"
            ),
        }

    content = _render_ranges(lines, merged)
    if merged:
        actual_start = merged[0][0]
        actual_end = merged[-1][1]
    else:
        # An empty interval begins at the earliest requested line and ends
        # immediately before it, preserving useful location metadata.
        actual_start = min(item["start_line"] for item in ranges)
        actual_end = actual_start - 1

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
        "content_truncated": False,
        "content_original_chars": len(content),
        "content_returned_chars": len(content),
        "start_line": actual_start,
        "end_line": actual_end,
        "returned_line_ranges": _range_dicts(merged),
        "total_lines": total_lines,
        "ranged": True,
    }


def _expanded_range(
    start_line: int,
    end_line: int,
    total_lines: int,
    minimum_lines: int,
) -> tuple[int, int]:
    """Expand a valid requested region around its center, shifting at file edges."""

    target_lines = min(minimum_lines, total_lines)
    returned_lines = end_line - start_line + 1
    if returned_lines >= target_lines:
        return start_line, end_line

    missing_lines = target_lines - returned_lines
    expanded_start = max(1, start_line - missing_lines // 2)
    expanded_end = min(
        total_lines,
        end_line + (missing_lines - missing_lines // 2),
    )

    # If one file edge constrained the balanced window, use the available room
    # on the other side so small requests still receive the configured context.
    remaining = target_lines - (expanded_end - expanded_start + 1)
    if remaining and expanded_start == 1:
        expanded_end = min(total_lines, expanded_end + remaining)
    elif remaining:
        expanded_start = max(1, expanded_start - remaining)
    return expanded_start, expanded_end


# Validate caller-supplied 1-based inclusive line ranges before reading.
def _validate_range(start_line: int, end_line: int) -> str | None:
    if start_line < 1:
        return "start_line must be >= 1"

    if end_line < 1:
        return "end_line must be >= 1"

    if end_line < start_line:
        return "end_line must be >= start_line"

    return None


def _validate_read_ranges(ranges: object) -> str | None:
    """Validate the optional public targeted-read representation."""

    if ranges is None:
        return None
    if not isinstance(ranges, list) or not ranges:
        return "ranges must be a non-empty list"
    if len(ranges) > MAX_REQUESTED_RANGES:
        return f"ranges may contain at most {MAX_REQUESTED_RANGES} items"

    for index, item in enumerate(ranges):
        if not isinstance(item, dict):
            return f"ranges[{index}] must be an object"
        if "start_line" not in item or "end_line" not in item:
            return f"ranges[{index}] requires start_line and end_line"
        if set(item) != {"start_line", "end_line"}:
            return f"ranges[{index}] may contain only start_line and end_line"
        item_start = item["start_line"]
        item_end = item["end_line"]
        if not _is_line_number(item_start) or not _is_line_number(item_end):
            return f"ranges[{index}] start_line and end_line must be integers"
        error = _validate_range(item_start, item_end)
        if error is not None:
            return f"ranges[{index}]: {error}"
    return None


def _validate_page_ranges(pages: object) -> str | None:
    """Validate the PDF-only page selection independently of line ranges."""

    if pages is None:
        return None
    if not isinstance(pages, list) or not pages:
        return "pages must be a non-empty list"
    if len(pages) > MAX_REQUESTED_PAGE_RANGES:
        return f"pages may contain at most {MAX_REQUESTED_PAGE_RANGES} items"

    for index, item in enumerate(pages):
        if not isinstance(item, dict):
            return f"pages[{index}] must be an object"
        if set(item) != {"start_page", "end_page"}:
            return f"pages[{index}] requires only start_page and end_page"
        start_page = item["start_page"]
        end_page = item["end_page"]
        if not _is_line_number(start_page) or not _is_line_number(end_page):
            return f"pages[{index}] start_page and end_page must be integers"
        if start_page < 1:
            return f"pages[{index}]: start_page must be >= 1"
        if end_page < start_page:
            return f"pages[{index}]: end_page must be >= start_page"
    return None


def _is_line_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge inclusive overlapping or adjacent ranges in source order."""

    merged: list[tuple[int, int]] = []
    for start_line, end_line in sorted(ranges):
        if merged and start_line <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_line))
        else:
            merged.append((start_line, end_line))
    return merged


def _range_dicts(ranges: Sequence[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"start_line": start, "end_line": end} for start, end in ranges]


def _render_ranges(
    lines: list[str],
    ranges: Sequence[tuple[int, int]],
) -> str:
    """Render source regions with unmistakable markers at every line gap."""
    parts: list[str] = []
    previous_end = None
    for start_line, end_line in ranges:
        if previous_end is not None and start_line > previous_end + 1:
            parts.append(
                f"<<< CODE SQUID: lines {previous_end + 1}-{start_line - 1} "
                "omitted from this read >>>\n"
            )
        parts.extend(lines[start_line - 1 : end_line])
        previous_end = end_line
    return "".join(parts)
