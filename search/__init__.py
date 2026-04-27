"""Search adapters for academic databases.

Each adapter exposes a `search(...)` function returning a list of dicts with
this unified schema:

    {
        "source":       str,    # e.g. "PubMed"
        "title":        str,
        "abstract":     str,
        "authors":      list[str],
        "journal":      str,
        "year":         int | None,
        "doi":          str,    # lowercased, no URL
        "pmid":         str,
        "url":          str,
        "study_design": str,    # best-guess from publication type
        "language":     str,
        "is_preprint":  bool,
    }
"""

from .pubmed import search as search_pubmed
from .europepmc import search as search_europepmc
from .crossref import search as search_crossref
from .openalex import search as search_openalex

__all__ = [
    "search_pubmed",
    "search_europepmc",
    "search_crossref",
    "search_openalex",
]
