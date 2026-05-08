"""Springer Nature adapter — supports both Meta API v2 and the Open Access API.

Both endpoints accept the same SPRINGER_API_KEY (one key, two products on the
dev portal). Caller picks `mode="meta"` (default, broad metadata for any
Springer publication) or `mode="oa"` (open-access subset, includes full-text
URLs).
"""
from __future__ import annotations

import re
from typing import Any

import requests

_BASE_META = "https://api.springernature.com/meta/v2/json"
_BASE_OA = "https://api.springernature.com/openaccess/json"

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


def _detect_design(content_type: str, title: str, abstract: str) -> str:
    if (content_type or "").lower() == "review":
        return "Review"
    blob = f"{title} {abstract}".lower()
    for keyword, label in _DESIGN_FROM_TEXT:
        if keyword in blob:
            return label
    return ""


def _build_query(
    keywords: str,
    start_date: str | None,
    end_date: str | None,
    languages: list[str] | None,
    include_preprints: bool,
) -> str:
    """Build a Springer 'q' string. Uses field qualifiers like keyword:(...), language:eng, etc.

    Springer date filtering is via `onlinedatefrom:YYYY-MM-DD onlinedateto:YYYY-MM-DD`.
    """
    parts: list[str] = []
    if keywords.strip():
        # Keep boolean operators; user typed AND/OR/NOT in the box.
        parts.append(f"({keywords})")

    if start_date:
        parts.append(f'onlinedatefrom:"{start_date}"')
    if end_date:
        parts.append(f'onlinedateto:"{end_date}"')

    if languages:
        # Springer language codes: eng, fre, spa, ger, etc.
        m = {
            "english": "eng", "french": "fre", "spanish": "spa", "german": "ger",
            "chinese": "chi", "japanese": "jpn", "portuguese": "por", "italian": "ita",
        }
        codes = [m.get(l.lower(), l[:3].lower()) for l in languages]
        if codes:
            parts.append("(" + " OR ".join(f'language:"{c}"' for c in codes) + ")")

    return " ".join(parts) if parts else keywords


def _strip_xml_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search(
    keywords: str,
    start_date: str | None = None,
    end_date: str | None = None,
    languages: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_preprints: bool = True,
    max_results: int = 50,
    api_key: str | None = None,
    mode: str = "meta",
    **_: Any,
) -> list[dict[str, Any]]:
    """Search Springer Nature.

    mode="meta"  -> /meta/v2/json (broader, requires Meta API key)
    mode="oa"    -> /openaccess/json (open-access only, full text URLs)
    """
    if not api_key:
        raise RuntimeError(
            "Springer Nature requires an API key — set SPRINGER_API_KEY in Streamlit secrets."
        )
    if not keywords.strip():
        return []

    base_url = _BASE_OA if mode == "oa" else _BASE_META

    q = _build_query(keywords, start_date, end_date, languages, include_preprints)
    params: dict[str, Any] = {
        "q": q,
        "p": min(max_results, 100),  # results per page (Springer max 100)
        "s": 1,                       # 1-indexed start
        "api_key": api_key,
    }

    try:
        resp = requests.get(base_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Springer ({mode}) request failed: {e}") from e

    out: list[dict[str, Any]] = []
    for r in data.get("records", []) or []:
        title = _strip_xml_tags(r.get("title") or "")
        abstract = _strip_xml_tags(r.get("abstract") or "")
        doi = (r.get("doi") or "").lower()
        journal = r.get("publicationName") or ""
        ctype = r.get("contentType") or ""
        is_preprint = ctype.lower() in {"preprint", "posted-content"}

        if not include_preprints and is_preprint:
            continue

        # Year from publicationDate (YYYY-MM-DD)
        year = None
        pdate = r.get("publicationDate") or r.get("onlineDate") or ""
        if pdate:
            try:
                year = int(pdate[:4])
            except (TypeError, ValueError):
                year = None

        authors: list[str] = []
        for c in r.get("creators", []) or []:
            name = c.get("creator") if isinstance(c, dict) else c
            if name:
                authors.append(name)

        # Resolve URL — prefer OA full-text when present, else DOI link.
        url = ""
        for u in r.get("url", []) or []:
            if isinstance(u, dict) and u.get("value"):
                url = u["value"]
                if u.get("format") in {"html", "pdf"}:
                    break
        if not url and doi:
            url = f"https://doi.org/{doi}"

        record = {
            "source": "Springer Nature" + (" OA" if mode == "oa" else ""),
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "pmid": "",
            "url": url,
            "study_design": _detect_design(ctype, title, abstract),
            "language": (r.get("language") or "").lower(),
            "is_preprint": is_preprint,
        }

        if study_designs and record["study_design"] not in study_designs:
            continue

        out.append(record)

    return out
