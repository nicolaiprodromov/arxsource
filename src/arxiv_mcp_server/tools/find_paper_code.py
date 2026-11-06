"""Find code and artifacts for an arXiv paper using the Hugging Face Hub API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import httpx
import mcp.types as types
from mcp.types import ToolAnnotations

from ..arxiv_api import (
    ArxivConnectionError,
    ArxivRateLimitError,
    ArxivTimeoutError,
    retry_with_backoff,
)
from ..config import Settings
from .arxiv_ids import bare_arxiv_id, parse_arxiv_id

logger = logging.getLogger("arxiv-mcp-server")
settings = Settings()

HF_HUB_URL = "https://huggingface.co"
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_CAP = 20
# Public URL prefix for each Hub repo type.
_REPO_URL_PREFIX = {
    "models": f"{HF_HUB_URL}/",
    "datasets": f"{HF_HUB_URL}/datasets/",
    "spaces": f"{HF_HUB_URL}/spaces/",
}
# Hub repo IDs are "name" or "namespace/name". Remote data is untrusted, so
# anything else is dropped rather than turned into a URL.
_HF_REPO_ID_RE = re.compile(r"[A-Za-z0-9][\w.-]*(/[\w.-]+)?", re.ASCII)
_MAX_URL_CHARS = 500

_NULLABLE_INT = {"type": ["integer", "null"]}
_NULLABLE_STR = {"type": ["string", "null"]}
FIND_PAPER_CODE_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "$defs": {
        "repos": {
            "type": "object",
            "properties": {
                "total": _NULLABLE_INT,
                "returned": {"type": "integer"},
                "has_more": {"type": ["boolean", "null"]},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "url": {"type": "string"},
                            "downloads": _NULLABLE_INT,
                            "likes": _NULLABLE_INT,
                        },
                        "required": ["id", "url", "downloads", "likes"],
                    },
                },
                "error": _NULLABLE_STR,
            },
            "required": ["total", "returned", "has_more", "items", "error"],
        }
    },
    "properties": {
        "status": {"type": "string"},
        "paper_id": {"type": "string"},
        "arxiv_id": {"type": "string"},
        "title": _NULLABLE_STR,
        "indexed_on_hf": {"type": ["boolean", "null"]},
        "hf_paper_url": _NULLABLE_STR,
        "github_repo": _NULLABLE_STR,
        "github_stars": _NULLABLE_INT,
        "project_page": _NULLABLE_STR,
        "upvotes": _NULLABLE_INT,
        "models": {"$ref": "#/$defs/repos"},
        "datasets": {"$ref": "#/$defs/repos"},
        "spaces": {"$ref": "#/$defs/repos"},
        "found": {"type": "boolean"},
        "message": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "paper_id",
        "arxiv_id",
        "indexed_on_hf",
        "github_repo",
        "models",
        "datasets",
        "spaces",
        "found",
        "message",
        "warnings",
    ],
}

find_paper_code_tool = types.Tool(
    name="find_paper_code",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    description=(
        "Find where the code and artifacts for an arXiv paper live: the GitHub "
        "repository (with stars) and project page, plus the most-downloaded "
        "Hugging Face models and datasets and linked Spaces. Uses the public "
        "Hugging Face Hub API (no key). A paper with nothing linked returns "
        "found=false, not an error; a failed sub-lookup is listed in warnings "
        "and the rest is still returned."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": (
                    "arXiv ID (for example: 2312.00752). A version suffix is "
                    "accepted and ignored."
                ),
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RESULTS_CAP,
                "description": (
                    "Maximum models, datasets, and Spaces to return per type "
                    f"(default {DEFAULT_MAX_RESULTS})."
                ),
            },
        },
        "required": ["paper_id"],
        "additionalProperties": False,
    },
    outputSchema=FIND_PAPER_CODE_OUTPUT_SCHEMA,
)


class HuggingFaceAPIError(Exception):
    """A Hugging Face Hub failure with a message that is safe to return."""


def _hf_headers() -> Dict[str, str]:
    """Build Hugging Face Hub request headers."""
    return {
        "Accept": "application/json",
        "User-Agent": (
            f"{settings.APP_NAME}/{settings.APP_VERSION} "
            "(https://github.com/blazickjp/arxiv-mcp-server; research tool)"
        ),
    }


async def _hf_get(
    client: httpx.AsyncClient, path: str, params: Dict[str, Any] | None = None
) -> httpx.Response:
    """GET a Hub API path with retry on 429/503 and timeout/connection errors.

    Non-retryable HTTP errors are re-raised as ``httpx.HTTPStatusError`` so
    callers can treat 404 as "not indexed" rather than as a failure.
    """

    async def request() -> httpx.Response:
        response = await client.get(
            f"{HF_HUB_URL}{path}", params=params, headers=_hf_headers()
        )
        response.raise_for_status()
        return response

    try:
        return await retry_with_backoff(
            request,
            max_retries=settings.ARXIV_MAX_RETRIES,
            initial_backoff=settings.ARXIV_INITIAL_BACKOFF,
            max_backoff=settings.ARXIV_MAX_BACKOFF,
            max_total_time=float(settings.ARXIV_MAX_TOTAL_TIME),
            operation_name="Hugging Face Hub API request",
        )
    except ArxivRateLimitError as exc:
        # The shared retry helper words its errors for arXiv; reword for the Hub.
        if exc.status_code == 503:
            message = "Hugging Face Hub is temporarily unavailable (HTTP 503)"
        else:
            message = (
                f"Hugging Face Hub rate limited the request (HTTP {exc.status_code})"
            )
        raise HuggingFaceAPIError(message) from exc
    except ArxivTimeoutError as exc:
        raise HuggingFaceAPIError("Hugging Face Hub request timed out") from exc
    except ArxivConnectionError as exc:
        raise HuggingFaceAPIError("Could not connect to Hugging Face Hub") from exc


def _http_error(exc: httpx.HTTPStatusError) -> HuggingFaceAPIError:
    """Describe an HTTP error without leaking upstream URLs (issue #166 class)."""
    status = exc.response.status_code if exc.response is not None else "unknown"
    return HuggingFaceAPIError(f"Hugging Face Hub API HTTP error (HTTP {status})")


async def _fetch_paper(client: httpx.AsyncClient, arxiv_id: str) -> Dict[str, Any]:
    """Return the Hub paper record, or ``{}`` if the Hub has not indexed it."""
    try:
        response = await _hf_get(client, f"/api/papers/{quote(arxiv_id, safe='')}")
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {}
        raise _http_error(exc) from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise HuggingFaceAPIError("Hugging Face Hub returned an unexpected response")
    return payload


async def _fetch_repos(
    client: httpx.AsyncClient, repo_type: str, arxiv_id: str, limit: int
) -> Tuple[List[Any], bool]:
    """Return the top repos tagged with the paper, and whether more exist."""
    try:
        response = await _hf_get(
            client,
            f"/api/{repo_type}",
            params={"filter": f"arxiv:{arxiv_id}", "sort": "downloads", "limit": limit},
        )
    except httpx.HTTPStatusError as exc:
        raise _http_error(exc) from exc
    payload = response.json()
    if not isinstance(payload, list):
        raise HuggingFaceAPIError("Hugging Face Hub returned an unexpected response")
    # The Hub paginates with a Link: rel="next" header, so its presence tells us
    # whether more repos exist without fetching them.
    return payload, "next" in response.links


def _int_or_none(value: Any) -> int | None:
    """Return ``value`` if it is an integer count (bools excluded), else None."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _url_or_none(value: Any, prefix: str = "http") -> str | None:
    """Return a remote URL only if it has the expected scheme/host prefix."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.startswith(prefix) or len(value) > _MAX_URL_CHARS:
        return None
    if not value.startswith(("https://", "http://")):
        return None
    if any(char.isspace() or not char.isprintable() for char in value):
        return None
    return value


def _repo_items(raw: Any, repo_type: str, limit: int) -> List[Dict[str, Any]]:
    """Normalize Hub repo entries to id/url/downloads/likes."""
    items: List[Dict[str, Any]] = []
    for entry in raw if isinstance(raw, list) else []:
        if len(items) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        repo_id = entry.get("id")
        if not isinstance(repo_id, str) or not _HF_REPO_ID_RE.fullmatch(repo_id):
            continue
        items.append(
            {
                "id": repo_id,
                "url": f"{_REPO_URL_PREFIX[repo_type]}{repo_id}",
                "downloads": _int_or_none(entry.get("downloads")),
                "likes": _int_or_none(entry.get("likes")),
            }
        )
    return items


def _repo_section(
    items: List[Dict[str, Any]], total: int | None, has_more: bool
) -> Dict[str, Any]:
    """Build one models/datasets/spaces section of the result."""
    if total is None and not has_more:
        # No further page and no Hub-side count: what we have is everything.
        total = len(items)
    elif total is not None:
        total = max(total, len(items))
    return {
        "total": total,
        "returned": len(items),
        "has_more": has_more,
        "items": items,
        "error": None,
    }


def _failed_section(message: str) -> Dict[str, Any]:
    """Build a section whose lookup failed; counts are unknown."""
    return {
        "total": None,
        "returned": 0,
        "has_more": None,
        "items": [],
        "error": message,
    }


def _failure_message(exc: BaseException) -> str:
    """Return a caller-safe description of a sub-request failure."""
    if isinstance(exc, HuggingFaceAPIError):
        return str(exc)
    return f"Unexpected error querying Hugging Face Hub ({type(exc).__name__})"


def _summary(payload: Dict[str, Any]) -> str:
    """One-line human-readable summary of what was found."""
    arxiv_id = payload["arxiv_id"]
    if not payload["found"]:
        if payload["indexed_on_hf"] is False:
            reason = "Hugging Face has not indexed this paper."
        elif payload["indexed_on_hf"] is None:
            reason = (
                "The paper lookup failed, so this may be incomplete (see warnings)."
            )
        else:
            reason = "Hugging Face lists nothing for it."
        return (
            f"No code repository, project page, or Hugging Face models, datasets, "
            f"or Spaces are linked to arXiv:{arxiv_id}. {reason} Code may still "
            "exist elsewhere; check the paper's abstract or comments for a link."
        )

    parts: List[str] = []
    if payload["github_repo"]:
        stars = payload.get("github_stars")
        star_text = f" ({stars:,} stars)" if stars is not None else ""
        parts.append(f"Code: {payload['github_repo']}{star_text}.")
    else:
        parts.append("No GitHub repository is linked.")
    if payload["project_page"]:
        parts.append(f"Project page: {payload['project_page']}.")

    counts: List[str] = []
    for repo_type, label in (
        ("models", "models"),
        ("datasets", "datasets"),
        ("spaces", "Spaces"),
    ):
        section = payload[repo_type]
        if section["error"] is not None:
            continue
        if section["total"] is not None:
            counts.append(f"{section['total']:,} {label}")
        else:
            counts.append(f"{section['returned']}+ {label}")
    if counts:
        parts.append(f"Hugging Face: {', '.join(counts)}.")
    return " ".join(parts)


def _bound_max_results(value: Any) -> int:
    """Clamp the caller-supplied per-type bound to the documented range."""
    if value is None:
        return DEFAULT_MAX_RESULTS
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RESULTS
    return max(1, min(parsed, MAX_RESULTS_CAP))


def _error_response(message: str) -> List[types.TextContent]:
    """Build an error payload that the server turns into an MCP tool error."""
    return [
        types.TextContent(
            type="text", text=json.dumps({"status": "error", "message": message})
        )
    ]


async def handle_find_paper_code(
    arguments: Dict[str, Any],
) -> List[types.TextContent] | Tuple[List[types.TextContent], Dict[str, Any]]:
    """Look up the code repository and Hub artifacts linked to an arXiv paper.

    Issues three concurrent Hub requests (paper record, models, datasets).
    Spaces come from the paper record because the Hub's Space listing cannot
    be filtered by paper. Each request fails independently: a failure is
    recorded on its section and in ``warnings`` while the rest is returned.
    Only when every request fails is the call reported as an error.

    Returns:
        On success, ``(content, structured)`` where ``content`` is the JSON
        text of ``structured`` (for clients without structured output support).
        On error, a single JSON error ``TextContent``.
    """
    try:
        raw_id = arguments.get("paper_id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return _error_response("paper_id is required")
        paper_id = parse_arxiv_id(raw_id)
        if paper_id is None:
            return _error_response("invalid arXiv ID format")

        # The Hub indexes and tags papers by bare ID only; strip vN for lookup.
        arxiv_id = bare_arxiv_id(paper_id)
        limit = _bound_max_results(arguments.get("max_results"))

        timeout = httpx.Timeout(
            connect=float(settings.ARXIV_CONNECT_TIMEOUT),
            read=float(settings.get_request_timeout()),
            write=30.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            paper_result, models_result, datasets_result = await asyncio.gather(
                _fetch_paper(client, arxiv_id),
                _fetch_repos(client, "models", arxiv_id, limit),
                _fetch_repos(client, "datasets", arxiv_id, limit),
                return_exceptions=True,
            )

        results = (paper_result, models_result, datasets_result)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
        failures = [r for r in results if isinstance(r, Exception)]
        for failure in failures:
            logger.warning("find_paper_code sub-request failed: %r", failure)
        if len(failures) == len(results):
            reasons = "; ".join(dict.fromkeys(_failure_message(f) for f in failures))
            return _error_response(
                f"Could not look up arXiv:{arxiv_id} on Hugging Face Hub: {reasons}"
            )

        warnings: List[str] = []
        paper: Dict[str, Any] = {}
        if isinstance(paper_result, Exception):
            paper_error = _failure_message(paper_result)
            warnings.append(
                f"Paper lookup failed ({paper_error}); GitHub repository, project "
                "page, and Spaces are unavailable."
            )
            indexed_on_hf: bool | None = None
            spaces = _failed_section(paper_error)
        else:
            paper = paper_result
            indexed_on_hf = bool(paper)
            linked_spaces = paper.get("linkedSpaces")
            space_items = _repo_items(linked_spaces, "spaces", limit)
            space_total = _int_or_none(paper.get("numTotalSpaces"))
            listed = len(linked_spaces) if isinstance(linked_spaces, list) else 0
            spaces = _repo_section(
                space_items,
                space_total,
                has_more=max(space_total or 0, listed) > len(space_items),
            )

        sections: Dict[str, Dict[str, Any]] = {"spaces": spaces}
        for repo_type, result, total_key in (
            ("models", models_result, "numTotalModels"),
            ("datasets", datasets_result, "numTotalDatasets"),
        ):
            if isinstance(result, Exception):
                message = _failure_message(result)
                warnings.append(
                    f"{repo_type.capitalize()} lookup failed ({message}); "
                    f"{repo_type} may be missing."
                )
                sections[repo_type] = _failed_section(message)
                continue
            raw_items, has_next = result
            items = _repo_items(raw_items, repo_type, limit)
            total = _int_or_none(paper.get(total_key))
            # Prefer the paper record's count: the Hub sends a next-page link
            # whenever a page is full, even if nothing follows it.
            has_more = total > len(items) if total is not None else has_next
            sections[repo_type] = _repo_section(items, total, has_more)

        github_repo = _url_or_none(paper.get("githubRepo"), "https://github.com/")
        project_page = _url_or_none(paper.get("projectPage"))
        title = paper.get("title")
        payload: Dict[str, Any] = {
            "status": "success",
            "paper_id": paper_id,
            "arxiv_id": arxiv_id,
            "title": title if isinstance(title, str) else None,
            "indexed_on_hf": indexed_on_hf,
            "hf_paper_url": (
                f"{HF_HUB_URL}/papers/{arxiv_id}" if indexed_on_hf else None
            ),
            "github_repo": github_repo,
            "github_stars": (
                _int_or_none(paper.get("githubStars")) if github_repo else None
            ),
            "project_page": project_page,
            "upvotes": _int_or_none(paper.get("upvotes")),
            "models": sections["models"],
            "datasets": sections["datasets"],
            "spaces": sections["spaces"],
            "found": bool(
                github_repo
                or project_page
                or any(sections[t]["items"] for t in ("models", "datasets", "spaces"))
            ),
            "message": "",
            "warnings": warnings,
        }
        payload["message"] = _summary(payload)

        content = [types.TextContent(type="text", text=json.dumps(payload, indent=2))]
        return content, payload

    except Exception as exc:
        logger.error("find_paper_code error: %s", exc)
        return _error_response(str(exc))
