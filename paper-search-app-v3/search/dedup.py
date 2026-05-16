"""Deduplication across multiple search sources.

Strategy:
1. Group records by DOI (lowercased) when present.
2. For records without DOI, group by normalized title (alnum lowercased, year ±1).
3. Within a group, prefer the record with the longest abstract; merge sources list.
"""
from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_title(t: str) -> str:
    return _NON_ALNUM.sub("", t.lower()).strip()


def _merge(group: list[dict[str, Any]]) -> dict[str, Any]:
    # Prefer the record with the longest abstract; merge `source` to a comma list.
    group_sorted = sorted(group, key=lambda r: len(r.get("abstract") or ""), reverse=True)
    primary = dict(group_sorted[0])
    sources = []
    for r in group_sorted:
        s = r.get("source", "")
        if s and s not in sources:
            sources.append(s)
    primary["source"] = ", ".join(sources)
    # Fill missing fields from later records.
    for r in group_sorted[1:]:
        for k, v in r.items():
            if not primary.get(k) and v:
                primary[k] = v
    return primary


def deduplicate(records: list[dict[str, Any]], fuzzy_threshold: int = 92) -> list[dict[str, Any]]:
    """Remove duplicate records from a merged list of search results."""
    if not records:
        return []

    by_doi: dict[str, list[dict[str, Any]]] = {}
    no_doi: list[dict[str, Any]] = []

    for r in records:
        doi = (r.get("doi") or "").strip().lower()
        if doi:
            by_doi.setdefault(doi, []).append(r)
        else:
            no_doi.append(r)

    merged: list[dict[str, Any]] = [_merge(g) for g in by_doi.values()]

    # Title-based clustering for records without DOIs.
    clusters: list[list[dict[str, Any]]] = []
    norms: list[str] = []
    for r in no_doi:
        t = _norm_title(r.get("title", ""))
        if not t:
            clusters.append([r])
            norms.append("")
            continue
        matched = False
        for i, n in enumerate(norms):
            if not n:
                continue
            # Quick prefix check, then fuzzy ratio.
            if fuzz.ratio(t, n) >= fuzzy_threshold:
                yr_a = clusters[i][0].get("year")
                yr_b = r.get("year")
                if yr_a is None or yr_b is None or abs((yr_a or 0) - (yr_b or 0)) <= 1:
                    clusters[i].append(r)
                    matched = True
                    break
        if not matched:
            clusters.append([r])
            norms.append(t)

    merged.extend(_merge(c) for c in clusters)
    return merged
