"""arXiv adapter — uses the public Atom export API (no key required).

arXiv is preprint-heavy and oriented toward physics, math, CS, and quant-bio.
For medical-context searches, the most relevant categories are:

    q-bio.*    — quantitative biology
    stat.AP    — statistics applications
    cs.LG, cs.AI — for ML-in-medicine searches

We expose all categories by default but the user can restrict via the
`categories` argument.
"""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

import requests

_BASE = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _build_search_query(
    keywords: str,
    start_date: str | None,
    end_date: str | None,
    categories: list[str] | None,
) -> str:
    parts: list[str] = []

    # Translate user's boolean keywords. arXiv expects field-prefixed terms
    # connected with AND/OR/ANDNOT. We default to `all:` for plain words.
    if keywords.strip():
        # Replace plain ANDNOT/NOT with ANDNOT for arXiv.
        # For multi-word phrases the user wrote in quotes, preserve them.
        kw = keywords.strip()
        kw = re.sub(r"\bNOT\b", "ANDNOT", kw)
        # Wrap unquoted bare words with the all: prefix only when there's no field already.
        # Simpler: just put the whole expression under `all:` parens.
        parts.append(f"all:({kw})")

    if start_date and end_date:
        # arXiv submittedDate format: YYYYMMDDHHMM
        s = start_date.replace("-", "") + "0000"
        e = end_date.replace("-", "") + "2359"
        parts.append(f"submittedDate:[{s} TO {e}]")

    if categories:
        cat_block = " OR ".join(f"cat:{c}" for c in categories)
        parts.append(f"({cat_block})")

    return " AND ".join(parts) if parts else f"all:{keywords}"


def _detect_design(title: str, abstract: str, primary_cat: str) -> str:
    blob = f"{title} {abstract}".lower()
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
    if primary_cat.startswith("q-bio"):
        return "Computational Biology"
    if primary_cat.startswith("stat"):
        return "Statistical"
    return "Preprint"


def search(
    keywords: str,
    start_date: str | None = None,
    end_date: str | None = None,
    languages: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_preprints: bool = True,
    max_results: int = 50,
    categories: list[str] | None = None,
    **_: Any,
) -> list[dict[str, Any]]:
    """Search arXiv. Returns empty list when include_preprints=False (arXiv is all preprints)."""
    if not include_preprints:
        # arXiv content is preprints only — respect the user's preference.
        return []

    if not keywords.strip():
        return []

    query = _build_search_query(keywords, start_date, end_date, categories)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": min(max_results, 200),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        resp = requests.get(_BASE, params=params, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"arXiv request failed: {e}") from e

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise RuntimeError(f"arXiv response was not valid XML: {e}") from e

    out: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _NS):
        title_el = entry.find("atom:title", _NS)
        summary_el = entry.find("atom:summary", _NS)
        published_el = entry.find("atom:published", _NS)
        id_el = entry.find("atom:id", _NS)

        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        url = (id_el.text or "").strip() if id_el is not None else ""

        # Year from <published>YYYY-MM-DDTHH:MM:SSZ</published>
        year = None
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except (TypeError, ValueError):
                year = None

        # Authors
        authors = [
            (a.findtext("atom:name", default="", namespaces=_NS) or "").strip()
            for a in entry.findall("atom:author", _NS)
        ]
        authors = [a for a in authors if a]

        # DOI when available
        doi_el = entry.find("arxiv:doi", _NS)
        doi = (doi_el.text or "").lower() if doi_el is not None else ""

        # Primary category (e.g. "q-bio.QM")
        primary_cat_el = entry.find("arxiv:primary_category", _NS)
        primary_cat = primary_cat_el.attrib.get("term", "") if primary_cat_el is not None else ""

        # Journal (rare on arXiv but present for some entries)
        journal_ref_el = entry.find("arxiv:journal_ref", _NS)
        journal = (journal_ref_el.text or "").strip() if journal_ref_el is not None else ""

        record = {
            "source": "arXiv",
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal or f"arXiv ({primary_cat})" if primary_cat else "arXiv",
            "year": year,
            "doi": doi,
            "pmid": "",
            "url": url,
            "study_design": _detect_design(title, abstract, primary_cat),
            "language": "",
            "is_preprint": True,
            "primary_category": primary_cat,
        }

        # Respect user's study-design filter when provided.
        if study_designs and record["study_design"] not in study_designs:
            continue

        out.append(record)

    return out
