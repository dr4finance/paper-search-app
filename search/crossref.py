"""Crossref adapter (REST). Free, all-discipline metadata via DOI registry."""
from __future__ import annotations

from typing import Any

import requests

_BASE = "https://api.crossref.org/works"


def _design_from_subject(subjects: list[str], title: str, abstract: str) -> str:
    blob = " ".join([*subjects, title, abstract]).lower()
    if "randomized" in blob or "randomised" in blob:
        return "RCT"
    if "meta-analysis" in blob or "meta analysis" in blob:
        return "Meta-Analysis"
    if "systematic review" in blob:
        return "Systematic Review"
    if "case-control" in blob or "case control" in blob:
        return "Case-Control"
    if "cohort" in blob:
        return "Cohort"
    if "review" in blob:
        return "Review"
    return ""


def search(
    keywords: str,
    start_date: str | None = None,
    end_date: str | None = None,
    languages: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_preprints: bool = True,
    max_results: int = 50,
    **_: Any,
) -> list[dict[str, Any]]:
    """Search Crossref. Note: Crossref does not natively filter by language or study design;
    we filter post-hoc for those fields when provided."""
    params: dict[str, Any] = {
        "query": keywords,
        "rows": min(max_results, 100),
        "select": (
            "DOI,title,author,container-title,published-print,published-online,"
            "abstract,subject,language,type,URL"
        ),
    }
    filters: list[str] = []
    if start_date:
        filters.append(f"from-pub-date:{start_date}")
    if end_date:
        filters.append(f"until-pub-date:{end_date}")
    # Crossref `type` filter: journal-article excludes preprints (which are 'posted-content').
    if not include_preprints:
        filters.append("type:journal-article")
    if filters:
        params["filter"] = ",".join(filters)

    headers = {
        "User-Agent": "paper-search-app/1.0 (mailto:paper-search-app@example.com)",
    }
    try:
        resp = requests.get(_BASE, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Crossref request failed: {e}") from e

    out: list[dict[str, Any]] = []
    for item in data.get("message", {}).get("items", []) or []:
        title = (item.get("title") or [""])[0]
        journal = (item.get("container-title") or [""])[0]
        doi = (item.get("DOI") or "").lower()
        url = item.get("URL", f"https://doi.org/{doi}" if doi else "")
        abstract = item.get("abstract", "") or ""
        # Crossref abstracts contain XML/JATS markup; quick strip:
        if abstract:
            import re
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

        year = None
        for k in ("published-print", "published-online", "issued"):
            dp = item.get(k, {}).get("date-parts")
            if dp and dp[0]:
                try:
                    year = int(dp[0][0])
                    break
                except (TypeError, ValueError):
                    pass

        authors: list[str] = []
        for a in item.get("author", []) or []:
            name = " ".join(filter(None, [a.get("given"), a.get("family")]))
            if name:
                authors.append(name)

        subjects = item.get("subject", []) or []
        ctype = item.get("type", "")
        is_preprint = ctype == "posted-content"

        # Post-hoc language filter
        lang = (item.get("language") or "").lower()
        if languages and lang and lang not in [l.lower() for l in languages]:
            continue

        record = {
            "source": "Crossref",
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "pmid": "",
            "url": url,
            "study_design": _design_from_subject(subjects, title, abstract),
            "language": lang,
            "is_preprint": is_preprint,
        }

        # Post-hoc study-design filter
        if study_designs and record["study_design"] not in study_designs:
            continue

        out.append(record)

    return out
