"""Europe PMC adapter (REST). Free, includes preprints."""
from __future__ import annotations

from typing import Any

import requests

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

_DESIGN_HINTS = {
    "RCT": "Randomized Controlled Trial",
    "Cohort": "Cohort",
    "Case-Control": "Case-Control",
    "Systematic Review": "Systematic Review",
    "Meta-Analysis": "Meta-Analysis",
    "Review": "Review",
}


def _build_query(
    keywords: str,
    start_date: str | None,
    end_date: str | None,
    languages: list[str] | None,
    study_designs: list[str] | None,
    include_preprints: bool,
) -> str:
    parts = [f"({keywords})"] if keywords.strip() else []

    if start_date and end_date:
        # Europe PMC supports FIRST_PDATE:[start TO end]
        parts.append(f"(FIRST_PDATE:[{start_date} TO {end_date}])")

    if languages:
        lang_block = " OR ".join(f'LANG:"{lang.lower()}"' for lang in languages)
        parts.append(f"({lang_block})")

    if study_designs:
        design_block = " OR ".join(f'PUB_TYPE:"{d}"' for d in study_designs if d)
        if design_block:
            parts.append(f"({design_block})")

    if not include_preprints:
        parts.append('NOT (SRC:"PPR")')

    return " AND ".join(parts) if parts else keywords


def _detect_design(pub_types: list[str]) -> str:
    blob = " ".join(pub_types).lower()
    for canon, hint in _DESIGN_HINTS.items():
        if hint.lower() in blob:
            return canon
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
    """Search Europe PMC."""
    query = _build_query(
        keywords, start_date, end_date, languages, study_designs, include_preprints
    )
    params = {
        "query": query,
        "format": "json",
        "pageSize": min(max_results, 100),
        "resultType": "core",
    }
    try:
        resp = requests.get(_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Europe PMC request failed: {e}") from e

    out: list[dict[str, Any]] = []
    for h in data.get("resultList", {}).get("result", []) or []:
        pmid = h.get("pmid", "") or ""
        doi = (h.get("doi", "") or "").lower()
        title = h.get("title", "") or ""
        abstract = h.get("abstractText", "") or ""
        journal = h.get("journalTitle", "") or ""
        year = None
        try:
            year = int(h.get("pubYear", "")) if h.get("pubYear") else None
        except (TypeError, ValueError):
            year = None

        authors_raw = h.get("authorString", "") or ""
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()]

        pub_types = h.get("pubTypeList", {}).get("pubType", []) or []
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        if pmid:
            url = f"https://europepmc.org/article/MED/{pmid}"
        elif h.get("id") and h.get("source"):
            url = f"https://europepmc.org/article/{h['source']}/{h['id']}"
        else:
            url = ""

        out.append({
            "source": "Europe PMC",
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "pmid": str(pmid),
            "url": url,
            "study_design": _detect_design(pub_types),
            "language": (h.get("language") or "").lower(),
            "is_preprint": h.get("source") == "PPR",
        })
    return out
