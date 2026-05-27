from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.utils.html import format_html
from django.utils.html import format_html_join

if TYPE_CHECKING:
    from django.utils.safestring import SafeString


def plain_snippet(text: str, *, keywords: tuple[str, ...], max_length: int) -> str:
    """Interface: return bounded plain text centered on the first keyword match."""
    normalized = text.strip()
    if not normalized or max_length <= 0:
        return ""

    return _snippet_window(normalized, keywords=keywords, max_length=max_length)


def highlighted_snippet(text: str, *, keywords: tuple[str, ...], max_length: int) -> SafeString:
    """Interface: return escaped snippet HTML with matched keywords wrapped in mark tags."""
    snippet = plain_snippet(text, keywords=keywords, max_length=max_length)
    if not snippet:
        return format_html("{}", "")

    pattern = _keyword_pattern(keywords)
    if pattern is None:
        return format_html("{}", snippet)

    chunks: list[SafeString] = []
    last_end = 0
    for match in pattern.finditer(snippet):
        chunks.append(format_html("{}", snippet[last_end : match.start()]))
        chunks.append(format_html("<mark>{}</mark>", match.group(0)))
        last_end = match.end()
    chunks.append(format_html("{}", snippet[last_end:]))
    return format_html_join("", "{}", ((chunk,) for chunk in chunks))


def _snippet_window(text: str, *, keywords: tuple[str, ...], max_length: int) -> str:
    """Extract a snippet no longer than max_length, using ellipses when truncated."""
    if len(text) <= max_length:
        return text

    pattern = _keyword_pattern(keywords)
    matched = pattern.search(text) if pattern is not None else None
    if matched is None:
        return f"{text[: max_length - 1].rstrip()}…"

    prefix = "…"
    suffix = "…"
    content_length = max_length - len(prefix) - len(suffix)
    match_center = matched.start() + ((matched.end() - matched.start()) // 2)
    start = max(match_center - (content_length // 2), 0)
    end = min(start + content_length, len(text))
    if end - start < content_length:
        start = max(end - content_length, 0)

    has_prefix = start > 0
    has_suffix = end < len(text)
    if not has_prefix:
        end = min(max_length - len(suffix), len(text))
    if not has_suffix:
        start = max(len(text) - (max_length - len(prefix)), 0)

    snippet = text[start:end].strip()
    return f"{prefix if has_prefix else ''}{snippet}{suffix if has_suffix else ''}"


def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile a case-insensitive regex from deduplicated non-blank keywords."""
    non_blank_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not non_blank_keywords:
        return None

    deduped = sorted(set(non_blank_keywords), key=lambda value: (-len(value), value.casefold()))
    return re.compile("|".join(re.escape(keyword) for keyword in deduped), flags=re.IGNORECASE)
