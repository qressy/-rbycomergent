from __future__ import annotations

import ipaddress
import re
import socket
from collections import Counter
from urllib.parse import urlparse

import httpx
from lxml import html

_FETCH_TIMEOUT_SECONDS = 5.0
_MAX_RESPONSE_BYTES = 1_000_000
_USER_AGENT = "ChatterSiftKeywordExtractor/1.0"
_MAX_KEYWORDS = 12

_STOPWORDS = frozenset(
    """
    a about above after again all am an and any are as at be because been before being below
    between both but by could did do does doing down during each few for from further had has
    have having he her here hers herself him himself his how i if in into is it its itself
    just me more most my myself no nor not now of off on once only or other our ours ourselves
    out over own same she should so some such than that the their theirs them themselves then
    there these they this those through to too under until up very was we were what when where
    which while who whom why will with you your yours yourself yourselves home page contact
    privacy terms cookies login sign signup register subscribe menu skip content learn read
    new free try our get started today click here also use using used can may one two three
    way ways things great best top easy simple help help us help me make made take taken come
    coming go going know known see seen want wanted need needed
    """.split()
)

_TOKEN_SPLIT = re.compile(r"[^\w&+#]+", re.UNICODE)


class KeywordExtractionError(Exception):
    """Raised when a URL cannot be fetched or parsed."""


def extract_keywords_from_url(raw_url: str) -> list[str]:
    """Fetches a webpage and returns up to _MAX_KEYWORDS candidate keywords."""

    url = _validate_url(raw_url)
    html_bytes = _fetch(url)
    return _extract(html_bytes)


def _validate_url(raw_url: str) -> str:
    candidate = (raw_url or "").strip()
    if not candidate:
        raise KeywordExtractionError("Enter a URL.")
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise KeywordExtractionError("URL must use http or https.")
    if not parsed.hostname:
        raise KeywordExtractionError("URL is missing a hostname.")
    _assert_public_host(parsed.hostname)
    return candidate


def _assert_public_host(hostname: str) -> None:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise KeywordExtractionError(f"Could not resolve {hostname}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise KeywordExtractionError("URL resolves to a non-public address.")


def _fetch(url: str) -> bytes:
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise KeywordExtractionError(f"Could not fetch URL: {exc}") from exc
    if response.status_code >= 400:
        raise KeywordExtractionError(f"URL returned HTTP {response.status_code}.")
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise KeywordExtractionError("URL did not return HTML.")
    body = response.content[:_MAX_RESPONSE_BYTES]
    return body


def _extract(body: bytes) -> list[str]:
    try:
        tree = html.fromstring(body)
    except (ValueError, html.etree.ParserError) as exc:
        raise KeywordExtractionError("Could not parse HTML.") from exc

    candidates: list[str] = []
    candidates += _phrases_from_meta(tree, "name", "keywords")
    candidates += _phrases_from_meta(tree, "property", "og:title")
    candidates += _phrases_from_meta(tree, "property", "og:description")
    candidates += _phrases_from_meta(tree, "name", "description")
    candidates += _phrases_from_text(tree, "//title")
    candidates += _phrases_from_text(tree, "//h1")
    candidates += _phrases_from_text(tree, "//h2")

    if not candidates:
        raise KeywordExtractionError("No keywords found on the page.")

    return _rank(candidates)


def _phrases_from_meta(tree, attr: str, value: str) -> list[str]:
    nodes = tree.xpath(f"//meta[@{attr}='{value}']/@content")
    return [str(node).strip() for node in nodes if node and str(node).strip()]


def _phrases_from_text(tree, xpath: str) -> list[str]:
    nodes = tree.xpath(xpath)
    return [node.text_content().strip() for node in nodes if node.text_content()]


def _rank(phrases: list[str]) -> list[str]:
    seen_keywords: list[str] = []
    seen_lower: set[str] = set()

    for phrase in phrases:
        for chunk in re.split(r"[|·•\-—–:,/]", phrase):
            cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", chunk.strip())
            if 2 <= len(cleaned.split()) <= 4 and _is_meaningful(cleaned):
                key = cleaned.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    seen_keywords.append(cleaned)

    if len(seen_keywords) >= _MAX_KEYWORDS:
        return seen_keywords[:_MAX_KEYWORDS]

    tokens = [
        token.lower()
        for phrase in phrases
        for token in _TOKEN_SPLIT.split(phrase)
        if len(token) >= 4 and token.lower() not in _STOPWORDS and not token.isdigit()
    ]
    counts = Counter(tokens)
    for token, _ in counts.most_common():
        if token not in seen_lower:
            seen_lower.add(token)
            seen_keywords.append(token)
        if len(seen_keywords) >= _MAX_KEYWORDS:
            break

    return seen_keywords[:_MAX_KEYWORDS]


def _is_meaningful(phrase: str) -> bool:
    words = [word.lower() for word in phrase.split()]
    if not words:
        return False
    non_stop = [word for word in words if word not in _STOPWORDS]
    return len(non_stop) >= 1
