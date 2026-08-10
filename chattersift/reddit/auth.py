"""Reddit OAuth bearer-token acquisition and caching.

Uses the client_credentials grant (app-only / userless), which works with
any Reddit app type and lets the server identify itself without a Reddit
user password. Bearer tokens are cached in-process for their lifetime and
refreshed on demand (e.g. when a 401 comes back).
"""
from __future__ import annotations

import os
import sys
import threading
import time

import httpx
from django.conf import settings

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_CACHE_KEY = "token"
_REFRESH_BUFFER_SECONDS = 60
_TOKEN_HTTP_TIMEOUT_SECONDS = 15.0

_token_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _diag(msg: str) -> None:
    print(f"[DIAG pid={os.getpid()} t={time.strftime('%H:%M:%S')}] {msg}", flush=True)
    sys.stdout.flush()


def is_oauth_configured() -> bool:
    """Return True when both client id and secret are set in settings."""
    return bool(
        getattr(settings, "CHATTERSIFT_REDDIT_CLIENT_ID", "")
        and getattr(settings, "CHATTERSIFT_REDDIT_CLIENT_SECRET", ""),
    )


def get_bearer_token(*, force_refresh: bool = False) -> str:
    """Return a valid bearer token, fetching or refreshing as needed."""
    if not is_oauth_configured():
        msg = "Reddit OAuth is not configured (missing client id or secret)."
        raise RuntimeError(msg)

    with _lock:
        if not force_refresh:
            cached = _token_cache.get(_CACHE_KEY)
            if cached is not None:
                token, expires_at = cached
                if expires_at - time.monotonic() > _REFRESH_BUFFER_SECONDS:
                    return token

        token, expires_in = _fetch_new_token()
        _token_cache[_CACHE_KEY] = (token, time.monotonic() + expires_in)
        return token


def invalidate_cached_token() -> None:
    """Drop the cached token so the next call re-fetches from Reddit."""
    with _lock:
        _token_cache.pop(_CACHE_KEY, None)


def _fetch_new_token() -> tuple[str, int]:
    client_id = settings.CHATTERSIFT_REDDIT_CLIENT_ID
    client_secret = settings.CHATTERSIFT_REDDIT_CLIENT_SECRET
    user_agent = settings.CHATTERSIFT_REDDIT_USER_AGENT

    _diag(f"reddit OAuth fetching new bearer token client_id_prefix={client_id[:4]}…")
    started = time.monotonic()
    with httpx.Client(timeout=_TOKEN_HTTP_TIMEOUT_SECONDS) as client:
        response = client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": user_agent},
        )
    elapsed = time.monotonic() - started

    if response.status_code != httpx.codes.OK:
        _diag(
            f"reddit OAuth token FAILED status={response.status_code} "
            f"body={response.text[:300]} in {elapsed:.2f}s",
        )
        response.raise_for_status()

    payload = response.json()
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    if not token:
        _diag(f"reddit OAuth token response missing access_token: {payload}")
        msg = "Reddit token response did not include an access_token."
        raise RuntimeError(msg)

    _diag(
        f"reddit OAuth token acquired expires_in={expires_in}s scope={payload.get('scope','?')} in {elapsed:.2f}s",
    )
    return token, expires_in
