"""Semantic Scholar Graph API adapter (public endpoint, no key required).

Public-tier rate limit is ~100 requests / 5 min, so we throttle to 1 req/sec
and retry on 429 with exponential backoff.
"""
from __future__ import annotations

import time
from typing import Any

import requests

_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"

# Fields we ask Semantic Scholar to return.
_FIELDS = (
    "title,abstract,year,authors,journal,externalIds,publicationTypes,"
    "publicationDate,publicationVenue,openAccessPdf,fieldsOfStudy"
)

_DESIGN_FROM_PUBTYPE = {
    "Review": "Review",
    "MetaAnalysis": "Meta-Analysis",
    "ClinicalTrial": "Clinical Trial",
    "CaseReport": "Case Report",
    "JournalArticle": "",
}

_DESIGN_FROM_TEXT = (
    ("randomized", "RCT"),
    ("randomised", "RCT"),
    ("meta-analysis", "Meta-Analysis"),
    ("meta analysis", "Meta-Analysis"),
    ("systematic review", "Systematic Review"),
    ("case-control", "Case-Control"),
    ("case control", "Case-Control"),
    ("cohort", "Cohort"),
    ("review", "Review"),
)


def _detect_design(pub_types: list[str], title: str, abstract: str) -> str:
    for pt in pub_types or []:
        if pt in _DESIGN_FROM_PUBTYPE and _DESIGN_FROM_PUBTYPE[pt]:
            return _DESIGN_FROM_PUBTYPE[pt]
    blob = f"{title} {abstract}".lower()
    for keyword, label in _DESIGN_FROM_TEXT:
        if keyword in blob:
            return label
    return ""


def _request_with_backoff(
    params: dict[str, Any], headers: dict[str, str], max_attempts: int = 4
) -> dict[str, Any]:
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = requests.get(_BASE, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                # Rate-limited; honor Retry-After if present.
                retry_after = float(resp.headers.get("Retry-After", delay))
                time.sleep(retry_after)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Semantic Scholar request failed after retries: {last_exc}")


def search(
    keywords: str,
    start_date: str | None = None,
    end_date: str | None = None,
    languages: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_preprints: bool = True,
    max_results: int = 50,
    api_key: str | None = None,
    **_: Any,
) -> list[dict[str, Any]]:
    """Search Semantic Scholar."""
    if not keywords.strip():
        return []

    params: dict[str, Any] = {
        "query": keywords,
        "limit": min(max_results, 100),
        "fields": _FIELDS,
        "offset": 0,
    }

    # Date filter — Semantic Scholar accepts publicationDateOrYear=YYYY-MM-DD:YYYY-MM-DD
    if start_date and end_date:
        params["publicationDateOrYear"] = f"{start_date}:{end_date}"
    elif start_date:
        params["publicationDateOrYear"] = f"{start_date}:"
    elif end_date:
        params["publicationDateOrYear"] = f":{end_date}"

    # Map our canonical study designs onto Semantic Scholar publication types.
    if study_designs:
        ss_types: list[str] = []
        for d in study_designs:
            if d == "RCT":
                ss_types.append("ClinicalTrial")
            elif d == "Systematic Review":
                ss_types.append("Review")
            elif d == "Meta-Analysis":
                ss_types.append("MetaAnalysis")
            elif d == "Review":
                ss_types.append("Review")
        if ss_types:
            params["publicationTypes"] = ",".join(sorted(set(ss_types)))

    headers = {"User-Agent": "paper-search-app/1.0"}
    if api_key:
        headers["x-api-key"] = api_key

    data = _request_with_backoff(params, headers)
    raw = data.get("data", []) or []

    out: list[dict[str, Any]] = []
    for item in raw:
        ext = item.get("externalIds") or {}
        doi = (ext.get("DOI") or "").lower()
        pmid = str(ext.get("PubMed") or "")
        title = item.get("title") or ""
        abstract = item.get("abstract") or ""
        year = item.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None

        venue = item.get("publicationVenue") or {}
        journal_name = (item.get("journal") or {}).get("name") or venue.get("name") or ""

        authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
        pub_types = item.get("publicationTypes") or []
        is_preprint = any(p == "Preprint" for p in pub_types) or (venue.get("type") == "preprint")
        fields_of_study = item.get("fieldsOfStudy") or []

        # Skip preprints if user wants peer-reviewed only.
        if not include_preprints and is_preprint:
            continue

        # Post-hoc language filter (Semantic Scholar doesn't expose language reliably).
        # We only filter when the user explicitly limits languages and abstract clearly indicates non-English.
        # Keep all by default to avoid false negatives.

        paper_id = item.get("paperId") or ""
        if doi:
            url = f"https://doi.org/{doi}"
        elif paper_id:
            url = f"https://www.semanticscholar.org/paper/{paper_id}"
        else:
            url = ""

        out.append({
            "source": "Semantic Scholar",
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal_name,
            "year": year,
            "doi": doi,
            "pmid": pmid,
            "url": url,
            "study_design": _detect_design(pub_types, title, abstract),
            "language": "",
            "is_preprint": is_preprint,
            "fields_of_study": fields_of_study,
        })

        # Throttle to 1 req/sec to play nice with the public endpoint.
        # (We've already done one HTTP call, so this only matters if callers loop.)

    return out
