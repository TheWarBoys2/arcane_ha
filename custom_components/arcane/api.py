"""A small async client for Arcane's REST API (https://getarcane.app)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import DEFAULT_TIMEOUT, MAX_PAGES, PAGE_SIZE


class ArcaneError(Exception):
    """Arcane answered with an error, or could not be reached."""


class ArcaneConnectionError(ArcaneError):
    """Arcane could not be reached."""


class ArcaneAuthError(ArcaneError):
    """Arcane rejected the API key."""


def normalize_url(url: str) -> str:
    """Return the Arcane base URL without a trailing slash or /api suffix."""
    url = url.strip().rstrip("/")
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url


class ArcaneClient:
    """Talks to one Arcane server with an API key (sent as X-API-Key)."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str, *, verify_ssl: bool = True) -> None:
        self._session = session
        self._base = normalize_url(url) + "/api"
        self._api_key = api_key.strip()
        self._ssl = None if verify_ssl else False

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with self._session.request(
                method,
                self._base + path,
                params=params,
                headers={"X-API-Key": self._api_key, "Accept": "application/json"},
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403):
                    raise ArcaneAuthError(await _error_detail(resp))
                if resp.status >= 400:
                    raise ArcaneError(f"HTTP {resp.status}: {await _error_detail(resp)}")
                text = await resp.text()
                if not text.strip():
                    return None
                try:
                    return json.loads(text)
                except ValueError as err:
                    raise ArcaneError(f"Arcane sent something that isn't JSON from {path}") from err
        except TimeoutError as err:
            raise ArcaneConnectionError(f"Timed out talking to Arcane at {self._base}") from err
        except aiohttp.ClientError as err:
            raise ArcaneConnectionError(f"Could not reach Arcane at {self._base}: {err}") from err

    async def _paged(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch every page of a paginated list. Returns (items, last response)."""
        items: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        for page in range(MAX_PAGES):
            query = {**(params or {}), "start": page * PAGE_SIZE, "limit": PAGE_SIZE}
            data = await self._request("GET", path, query)
            last = data if isinstance(data, dict) else {}
            batch = last.get("data") if isinstance(last.get("data"), list) else []
            items.extend(i for i in batch if isinstance(i, dict))
            total = (last.get("pagination") or {}).get("totalItems") or 0
            if not batch or len(items) >= total:
                break
        return items, last

    async def list_environments(self) -> list[dict[str, Any]]:
        """List the environments this key can see."""
        items, _ = await self._paged("/environments")
        return [i for i in items if i.get("id") is not None]

    async def list_containers(self, env_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """List every container in an environment, with a CPU/memory sample each.

        Sorting by cpuUsage (Arcane 2.13+) makes Arcane attach a resourceSample
        to each running container, so stats come from one request per poll.
        """
        items, last = await self._paged(
            f"/environments/{quote(env_id, safe='')}/containers",
            {"sort": "cpuUsage", "order": "desc"},
        )
        counts = last.get("counts") if isinstance(last.get("counts"), dict) else {}
        return items, counts

    async def container_action(self, env_id: str, container_id: str, action: str) -> None:
        """Run start, stop, restart or redeploy on a container."""
        await self._request(
            "POST",
            f"/environments/{quote(env_id, safe='')}/containers/{quote(container_id, safe='')}/{action}",
        )


async def _error_detail(resp: aiohttp.ClientResponse) -> str:
    """Pull a readable message out of an Arcane (huma) error body."""
    try:
        body = json.loads(await resp.text())
    except (aiohttp.ClientError, UnicodeDecodeError, ValueError):
        return getattr(resp, "reason", None) or "error"
    if isinstance(body, dict):
        for key in ("detail", "error", "message", "title"):
            if isinstance(body.get(key), str) and body[key]:
                return body[key]
    return getattr(resp, "reason", None) or "error"
