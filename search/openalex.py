"""OpenAlex adapter (REST). Free, all-discipline, includes citations and concepts."""
from __future__ import annotations

from typing import Any

import requests

_BASE = "https://api.openalex.org/works"


def _decode_inverted_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            pos[p] = word
    if not pos:
        return ""
    ordered = [pos[i] for i in sorted(pos.keys())]
    return " ".join(ordered)


def _design_from_text(title: str, abstract: str, concepts: list[str]) -> str:
    blob = " ".join([title, abstract, *concepts]).lower()
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
    """Search OpenAlex."""
    filters: list[str] = []
    if start_date:
        filters.append(f"from_publication_date:{start_date}")
    if end_date:
        filters.append(f"to_publication_date:{end_date}")
    if languages:
        # OpenAlex uses ISO 639-1 codes
        iso = []
        m = {"english": "en", "french": "fr", "spanish": "es", "german": "de",
             "chinese": "zh", "japanese": "ja", "portuguese": "pt", "italian": "it"}
        for l in languages:
            iso.append(m.get(l.lower(), l.lower()))
        filters.append("language:" + "|".join(iso))
    if not include_preprints:
        filters.append("type:article")

    params: dict[str, Any] = {
        "search": keywords,
        "per-page": min(max_results, 200),
        "mailto": "paper-search-app@example.com",
    }
    if filters:
        params["filter"] = ",".join(filters)

    try:
        resp = requests.get(_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"OpenAlex request failed: {e}") from e

    out: list[dict[str, Any]] = []
    for w in data.get("results", []) or []:
        title = w.get("title") or w.get("display_name") or ""
        abstract = _decode_inverted_abstract(w.get("abstract_inverted_index"))
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        year = w.get("publication_year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None

        host = w.get("primary_location", {}).get("source", {}) or {}
        journal = host.get("display_name", "") or ""

        authors: list[str] = []
        for a in w.get("authorships", []) or []:
            name = a.get("author", {}).get("display_name")
            if name:
                authors.append(name)

        concepts = [c.get("display_name", "") for c in w.get("concepts", []) or []]
        url = (w.get("primary_location", {}) or {}).get("landing_page_url") or (
            f"https://doi.org/{doi}" if doi else w.get("id", "")
        )

        wtype = w.get("type", "")
        is_preprint = wtype in {"posted-content", "preprint"}

        record = {
            "source": "OpenAlex",
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "pmid": "",
            "url": url,
            "study_design": _design_from_text(title, abstract, concepts),
            "language": (w.get("language") or "").lower(),
            "is_preprint": is_preprint,
        }

        if study_designs and record["study_design"] not in study_designs:
            continue
        out.append(record)

    return out
