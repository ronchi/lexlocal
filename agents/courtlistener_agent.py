"""
CourtListener REST API v4 — semantic/keyword opinion search and document download.

API docs: https://wiki.free.law/c/courtlistener/help/api/rest/v4/search
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import httpx

import re

CL_BASE     = "https://www.courtlistener.com"
CL_SEARCH   = f"{CL_BASE}/api/rest/v4/search/"
CL_CLUSTERS = f"{CL_BASE}/api/rest/v4/clusters/"


def _strip_html(text: str) -> str:
    """Remove HTML tags (e.g. <mark>…</mark> from highlight=on) from a string."""
    return re.sub(r"<[^>]+>", "", text or "").strip()

# CourtListener throttles anonymous requests; a free token raises limits.
# Register at https://www.courtlistener.com/register/
_DEFAULT_TIMEOUT = 30   # seconds for search
_DOWNLOAD_TIMEOUT = 120 # seconds per document


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_PER_PAGE      = 50   # CourtListener max results per API request
_SEARCH_TIMEOUT = 60  # seconds per paginated request


def search_opinions(
    query: str,
    api_token: str = "",
    semantic: bool = True,
    court: str = "",
    filed_after: str = "",
    filed_before: str = "",
    page_size: int = 20,
) -> dict:
    """
    Search CourtListener for court opinions, with automatic pagination.

    When *query* is provided the full-text /search/ endpoint is used.
    When *query* is empty the /clusters/ browse endpoint is used instead —
    the search endpoint requires a query term and returns 400 without one.

    Parameters
    ----------
    query       : Full-text or natural-language search query (may be empty).
    api_token   : Optional CourtListener API token (raises rate limits).
    semantic    : True → semantic search; False → BM25.  Ignored without a query.
    court       : Court slug filter, e.g. "scotus", "ca9", "txca15".
    filed_after : Lower date bound (YYYY-MM-DD).
    filed_before: Upper date bound (YYYY-MM-DD).
    page_size   : Maximum total results (up to 1000); pages fetched automatically.

    Returns
    -------
    Dict with keys: count, results (trimmed to page_size), next, previous.
    """
    page_size = int(page_size)
    has_query = bool(query.strip())

    headers: dict[str, str] = {}
    if api_token.strip():
        headers["Authorization"] = f"Token {api_token.strip()}"

    with httpx.Client(
        timeout=_SEARCH_TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:
        if has_query:
            return _search_endpoint(
                client, query.strip(), semantic,
                court, filed_after, filed_before, page_size,
            )
        else:
            return _clusters_endpoint(
                client, court, filed_after, filed_before, page_size,
            )


def _paginate(client: "httpx.Client", first_url: str,
              params: dict, page_size: int) -> dict:
    """
    Follow CourtListener pagination until *page_size* results are collected
    or there are no more pages.  Returns the assembled response dict.
    """
    all_results: list[dict] = []
    total_count = 0
    next_url: str | None = first_url
    first_page = True

    while next_url and len(all_results) < page_size:
        if first_page:
            resp = client.get(next_url, params=params)
            first_page = False
        else:
            resp = client.get(next_url)   # next_url already encodes all params
        if not resp.is_success:
            body = ""
            try:
                body = " — " + str(resp.json())
            except Exception:
                body = f" — {resp.text[:300]}"
            raise httpx.HTTPStatusError(
                f"Client error '{resp.status_code} {resp.reason_phrase}' "
                f"for url '{resp.url}'{body}",
                request=resp.request,
                response=resp,
            )
        data = resp.json()

        if total_count == 0:
            raw_count = data.get("count", 0)
            # /clusters/ returns count as a deferred URL, not an int
            total_count = raw_count if isinstance(raw_count, int) else 0

        all_results.extend(data.get("results", []))
        next_url = data.get("next")

    return {
        "count":    total_count,
        "results":  all_results[:page_size],
        "next":     next_url,
        "previous": None,
    }


def _search_endpoint(
    client: "httpx.Client",
    query: str,
    semantic: bool,
    court: str,
    filed_after: str,
    filed_before: str,
    page_size: int,
) -> dict:
    """Full-text search via /api/rest/v4/search/ (requires a query term)."""
    params: dict[str, Any] = {
        "q":         query,
        "type":      "o",
        "order_by":  "score desc",
        "highlight": "on",
        "page_size": min(_PER_PAGE, page_size),
    }
    if semantic:
        params["semantic"] = "true"
    if court.strip():
        params["court"] = court.strip()
    if filed_after.strip():
        params["filed_after"] = filed_after.strip()
    if filed_before.strip():
        params["filed_before"] = filed_before.strip()

    return _paginate(client, CL_SEARCH, params, page_size)


CL_DOCKETS = f"{CL_BASE}/api/rest/v4/dockets/"


def _get_court_docket_ids(client: "httpx.Client", court: str) -> set[str]:
    """
    Return the set of all docket IDs that belong to *court* by paging through
    /api/rest/v4/dockets/?court=<slug>.  Called once per browse search so we
    can filter clusters client-side (the /clusters/ endpoint has no court filter).
    """
    docket_ids: set[str] = []
    next_url: str | None = CL_DOCKETS
    first = True
    params = {"court": court, "page_size": _PER_PAGE}

    while next_url:
        resp = client.get(next_url, params=params) if first else client.get(next_url)
        first = False
        if not resp.is_success:
            break
        data = resp.json()
        for d in (data.get("results") or []):
            if isinstance(d, dict):
                did = str(d.get("id", ""))
                if did:
                    docket_ids.append(did)
        next_url = data.get("next")

    return set(docket_ids)


def _docket_id_from_cluster(c: dict) -> str | None:
    """Extract the numeric docket ID from a cluster record's docket field."""
    docket_field = c.get("docket") or ""
    if isinstance(docket_field, str):
        parts = [p for p in docket_field.rstrip("/").split("/") if p]
        if parts and parts[-1].isdigit():
            return parts[-1]
    elif isinstance(docket_field, dict):
        did = str(docket_field.get("id", ""))
        return did or None
    return None


def _clusters_endpoint(
    client: "httpx.Client",
    court: str,
    filed_after: str,
    filed_before: str,
    page_size: int,
) -> dict:
    """
    Browse opinions via /api/rest/v4/clusters/ — works without a query term.

    The /clusters/ endpoint only allows date_filed__gte / date_filed__lte as
    server-side filters; every court filter variant is rejected with 400.
    When a court is requested we pre-fetch ALL docket IDs for that court from
    /api/rest/v4/dockets/?court=<slug>, then keep only the clusters whose
    docket ID is in that set.  This is one extra paginated pass over the
    dockets endpoint (done once per search, not per cluster page).
    """
    date_params: dict[str, Any] = {
        "page_size": min(_PER_PAGE, page_size),
    }
    if filed_after.strip():
        date_params["date_filed__gte"] = filed_after.strip()
    if filed_before.strip():
        date_params["date_filed__lte"] = filed_before.strip()

    court = court.strip()

    # Pre-fetch docket IDs for the requested court (empty set = no filter)
    court_docket_ids: set[str] = set()
    if court:
        court_docket_ids = _get_court_docket_ids(client, court)

    all_results: list[dict] = []
    total_count  = 0
    next_url: str | None = CL_CLUSTERS
    first_page   = True

    while next_url and len(all_results) < page_size:
        if first_page:
            resp = client.get(next_url, params=date_params)
            first_page = False
        else:
            resp = client.get(next_url)

        if not resp.is_success:
            body = ""
            try:
                body = " — " + str(resp.json())
            except Exception:
                body = f" — {resp.text[:300]}"
            raise httpx.HTTPStatusError(
                f"Client error '{resp.status_code} {resp.reason_phrase}' "
                f"for url '{resp.url}'{body}",
                request=resp.request, response=resp,
            )

        data     = resp.json()
        clusters = data.get("results", [])
        next_url = data.get("next")
        if total_count == 0:
            raw_count = data.get("count", 0)
            total_count = raw_count if isinstance(raw_count, int) else 0

        if not clusters:
            break

        for c in clusters:
            if court_docket_ids:
                did = _docket_id_from_cluster(c)
                if not did or did not in court_docket_ids:
                    continue   # skip — belongs to a different court
            all_results.append(_normalize_cluster(c))

    return {
        "count":    total_count,
        "results":  all_results[:page_size],
        "next":     next_url,
        "previous": None,
    }


def _normalize_cluster(c: dict) -> dict:
    """
    Convert a /clusters/ record into the shape that format_results_table,
    make_checkbox_choices, and download_opinions expect (i.e. the shape that
    /search/ results have).

    The /clusters/ endpoint may return related objects (sub_opinions, citations)
    as either nested dicts OR bare URL strings depending on the API version and
    serializer depth.  All fields are handled defensively.
    """
    # Build citation strings — each item is either a dict or a URL string
    citations: list[str] = []
    for cit in (c.get("citations") or []):
        if isinstance(cit, dict):
            parts = [
                str(cit.get("volume", "")),
                str(cit.get("reporter", "")),
                str(cit.get("page", "")),
            ]
            s = " ".join(p for p in parts if p and p != "None")
            if s.strip():
                citations.append(s.strip())
        # If it's a string URL we have nothing human-readable to show; skip it.

    # sub_opinions → opinions — each item is either a dict or a URL string
    opinions: list[dict] = []
    for op in (c.get("sub_opinions") or []):
        if isinstance(op, dict):
            url = op.get("download_url") or op.get("file_with_date") or ""
            if url:
                opinions.append({"download_url": url})
        elif isinstance(op, str) and op.startswith("http"):
            # Bare URL — record it as a download candidate
            opinions.append({"download_url": op})

    # Court string — docket may be a nested dict or a bare URL string
    docket = c.get("docket") or {}
    court_str = ""
    if isinstance(docket, dict):
        court_str = str(docket.get("court_id") or docket.get("court") or "")

    return {
        "cluster_id":            c.get("id", ""),
        "caseName":              c.get("case_name") or c.get("case_name_full") or "Unknown",
        "dateFiled":             c.get("date_filed", ""),
        "court":                 court_str,
        "court_citation_string": court_str,
        "citation":              citations,
        "opinions":              opinions,
        "absolute_url":          c.get("absolute_url", ""),
    }


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def format_results_table(results: list[dict]) -> list[list]:
    """
    Convert raw API results into display rows for gr.Dataframe.
    Columns: ID | Case Name | Court | Date Filed | Citations | PDF?
    """
    rows = []
    for r in results:
        cluster_id = r.get("cluster_id", "")
        case_name = _strip_html(r.get("caseName") or r.get("caseNameFull") or "Unknown")
        court = _strip_html(r.get("court_citation_string") or r.get("court") or "")
        date = (r.get("dateFiled") or r.get("dateArgued") or "").strip()
        citations = ", ".join(_strip_html(c) for c in (r.get("citation") or []))
        opinions = r.get("opinions") or []
        has_pdf = any(op.get("download_url") for op in opinions)
        pdf_marker = "✓" if has_pdf else "—"
        rows.append([cluster_id, case_name, court, date, citations, pdf_marker])
    return rows


def make_checkbox_choices(results: list[dict]) -> list[str]:
    """
    Build human-readable checkbox labels from search results.
    Format: "<cluster_id> | <case_name> | <court> | <date>"
    """
    choices = []
    for r in results:
        cid = r.get("cluster_id", "?")
        name = _strip_html(r.get("caseName") or r.get("caseNameFull") or "Unknown")
        court = _strip_html(r.get("court_citation_string") or r.get("court") or "")
        date = (r.get("dateFiled") or "").strip()
        label = f"{cid} | {name[:70]} | {court} | {date}"
        choices.append(label)
    return choices


def extract_cluster_id(checkbox_label: str) -> str:
    """Parse the cluster ID from a checkbox label string."""
    return checkbox_label.split(" | ")[0].strip()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_opinions(
    results: list[dict],
    selected_labels: list[str],
    dest_folder: Path,
    api_token: str = "",
    progress_cb: Callable[[str], None] | None = None,
) -> list[Path]:
    """
    Download the document for each selected opinion into dest_folder.

    Each opinion's `opinions` array may contain multiple document variants
    (majority, dissent, concurrence). We download the first variant that has
    a download_url; we prefer PDFs but will accept HTML if that is all that
    is available.

    Parameters
    ----------
    results         : Raw results list from search_opinions().
    selected_labels : Checkbox label strings (from make_checkbox_choices()).
    dest_folder     : Directory where files will be saved (created if needed).
    api_token       : CourtListener token for authenticated downloads.
    progress_cb     : Optional callback for live progress messages.

    Returns
    -------
    List of Path objects for successfully downloaded files.
    """
    dest_folder.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    selected_ids = {extract_cluster_id(lbl) for lbl in selected_labels}
    to_download = [r for r in results if str(r.get("cluster_id", "")) in selected_ids]

    if not to_download:
        log("⚠ No matching results found for selected IDs.")
        return []

    headers: dict[str, str] = {}
    if api_token.strip():
        headers["Authorization"] = f"Token {api_token.strip()}"

    downloaded: list[Path] = []

    with httpx.Client(
        timeout=_DOWNLOAD_TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for i, r in enumerate(to_download, 1):
            cluster_id = r.get("cluster_id", "")
            case_name = (r.get("caseName") or r.get("caseNameFull") or "doc").strip()
            safe_name = "".join(
                c if (c.isalnum() or c in " _-") else "_" for c in case_name
            )[:80].strip()

            log(f"[{i}/{len(to_download)}] {case_name[:70]}")

            opinions = r.get("opinions") or []
            if not opinions:
                log(f"  ⚠ No opinion documents listed for cluster {cluster_id}.")
                continue

            # Prefer PDF variants; fall back to HTML
            sorted_opinions = sorted(
                opinions,
                key=lambda op: (
                    0 if _is_pdf_url(op.get("download_url", "")) else 1
                ),
            )

            got_file = False
            for op in sorted_opinions:
                url = op.get("download_url", "").strip()
                if not url:
                    continue
                if not url.startswith("http"):
                    url = CL_BASE + url

                log(f"  ↳ Fetching: {url}")
                try:
                    resp = client.get(url)
                    resp.raise_for_status()

                    content_type = resp.headers.get("content-type", "")

                    # ── Opinion API response? ────────────────────────────────
                    # The /clusters/ browse path stores opinion API endpoint
                    # URLs (e.g. /api/rest/v4/opinions/12345/) as download_url.
                    # Fetching those returns a JSON metadata object; we need to
                    # follow the real download_url inside it, or fall back to
                    # the plain_text / html fields if no file URL is present.
                    if "json" in content_type or resp.content[:1] == b"{":
                        try:
                            opinion_data = resp.json()
                        except Exception:
                            opinion_data = {}

                        if isinstance(opinion_data, dict) and (
                            "download_url" in opinion_data
                            or "plain_text" in opinion_data
                            or "html_with_citations" in opinion_data
                        ):
                            real_url = (opinion_data.get("download_url") or "").strip()
                            if real_url:
                                log(f"  ↳ Resolved opinion API → {real_url}")
                                resp2 = client.get(real_url)
                                resp2.raise_for_status()
                                resp = resp2
                                content_type = resp.headers.get("content-type", "")
                                url = real_url
                            else:
                                # No file URL — save plain text or HTML inline
                                text = (opinion_data.get("plain_text") or "").strip()
                                html = (
                                    opinion_data.get("html_with_citations")
                                    or opinion_data.get("html_lawbox")
                                    or opinion_data.get("html")
                                    or ""
                                ).strip()
                                body = text or _strip_html(html)
                                if body:
                                    suffix = ".txt"
                                    out_name = f"cl_{cluster_id}_{safe_name}{suffix}"
                                    out_path = dest_folder / out_name
                                    counter = 0
                                    while out_path.exists():
                                        counter += 1
                                        out_path = dest_folder / f"cl_{cluster_id}_{safe_name}_{counter}{suffix}"
                                    out_path.write_text(body, encoding="utf-8")
                                    log(f"  ✓ Saved text {out_path.name}  ({len(body):,} chars)")
                                    downloaded.append(out_path)
                                    got_file = True
                                else:
                                    log(f"  ⚠ Opinion API returned JSON with no usable content.")
                                break
                    # ── End opinion API handling ─────────────────────────────

                    if got_file:
                        break

                    suffix = _choose_suffix(url, content_type)
                    out_name = f"cl_{cluster_id}_{safe_name}{suffix}"
                    out_path = dest_folder / out_name

                    # Avoid clobbering if multiple opinions for same cluster
                    counter = 0
                    while out_path.exists():
                        counter += 1
                        out_path = dest_folder / f"cl_{cluster_id}_{safe_name}_{counter}{suffix}"

                    out_path.write_bytes(resp.content)
                    size_kb = len(resp.content) // 1024
                    log(f"  ✓ Saved {out_path.name}  ({size_kb:,} KB)")
                    downloaded.append(out_path)
                    got_file = True
                    break  # one document per opinion entry is enough

                except httpx.HTTPStatusError as exc:
                    log(f"  ✗ HTTP {exc.response.status_code} for {url}")
                except Exception as exc:
                    log(f"  ✗ Error downloading {url}: {exc}")

            if not got_file:
                # Fallback: try to fetch the case page HTML from CourtListener
                abs_url = r.get("absolute_url", "")
                if abs_url:
                    if not abs_url.startswith("http"):
                        abs_url = CL_BASE + abs_url
                    log(f"  ↳ No PDF found — saving case page HTML: {abs_url}")
                    try:
                        resp = client.get(abs_url)
                        resp.raise_for_status()
                        out_path = dest_folder / f"cl_{cluster_id}_{safe_name}.html"
                        out_path.write_bytes(resp.content)
                        log(f"  ✓ Saved HTML page {out_path.name}")
                        downloaded.append(out_path)
                    except Exception as exc:
                        log(f"  ✗ Could not fetch case page: {exc}")
                else:
                    log(f"  ✗ No downloadable document for cluster {cluster_id}.")

    return downloaded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_pdf_url(url: str) -> bool:
    """Heuristic: does this URL point to a PDF?"""
    url_lower = url.lower()
    return url_lower.endswith(".pdf") or "/pdf/" in url_lower or "pdf" in url_lower


def _choose_suffix(url: str, content_type: str) -> str:
    """Pick a file extension based on URL and content-type header."""
    ct = content_type.lower()
    if "pdf" in ct or _is_pdf_url(url):
        return ".pdf"
    if "html" in ct:
        return ".html"
    if "text" in ct:
        return ".txt"
    if "wordprocessingml" in ct or "docx" in ct:
        return ".docx"
    # Default to PDF for unknown types from CourtListener
    return ".pdf"
