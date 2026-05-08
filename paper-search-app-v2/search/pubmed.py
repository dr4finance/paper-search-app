"""PubMed adapter using NCBI E-utilities (Biopython)."""
from __future__ import annotations

from typing import Any

from Bio import Entrez


# Map PubMed publication type strings to our canonical study designs.
_DESIGN_MAP = {
    "Randomized Controlled Trial": "RCT",
    "Clinical Trial": "Clinical Trial",
    "Meta-Analysis": "Meta-Analysis",
    "Systematic Review": "Systematic Review",
    "Review": "Review",
    "Case Reports": "Case Report",
    "Observational Study": "Observational",
    "Comparative Study": "Comparative",
    "Multicenter Study": "Multicenter",
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
        # PubMed expects YYYY/MM/DD
        parts.append(
            f'("{start_date.replace("-", "/")}"[Date - Publication] : '
            f'"{end_date.replace("-", "/")}"[Date - Publication])'
        )

    if languages:
        lang_block = " OR ".join(f'"{lang.lower()}"[Language]' for lang in languages)
        parts.append(f"({lang_block})")

    if study_designs:
        # Translate our canonical names into PubMed publication types.
        pub_types: list[str] = []
        for d in study_designs:
            if d == "RCT":
                pub_types.append("Randomized Controlled Trial[Publication Type]")
            elif d == "Cohort":
                pub_types.append("Cohort Studies[MeSH Terms]")
            elif d == "Case-Control":
                pub_types.append("Case-Control Studies[MeSH Terms]")
            elif d == "Systematic Review":
                pub_types.append("Systematic Review[Publication Type]")
            elif d == "Meta-Analysis":
                pub_types.append("Meta-Analysis[Publication Type]")
            elif d == "Observational":
                pub_types.append("Observational Study[Publication Type]")
        if pub_types:
            parts.append("(" + " OR ".join(pub_types) + ")")

    if not include_preprints:
        # Exclude preprints if user wants peer-reviewed only.
        parts.append('NOT "preprint"[Publication Type]')

    return " AND ".join(parts) if parts else keywords


def _parse_record(rec: dict[str, Any]) -> dict[str, Any]:
    article = rec.get("MedlineCitation", {}).get("Article", {})
    pmid = str(rec.get("MedlineCitation", {}).get("PMID", ""))

    title = article.get("ArticleTitle", "") or ""
    abstract_parts = article.get("Abstract", {}).get("AbstractText", []) or []
    if isinstance(abstract_parts, list):
        abstract = " ".join(str(p) for p in abstract_parts)
    else:
        abstract = str(abstract_parts)

    journal = article.get("Journal", {}).get("Title", "") or ""

    # Year
    year: int | None = None
    pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    y = pub_date.get("Year") or pub_date.get("MedlineDate", "")[:4]
    try:
        year = int(str(y))
    except (TypeError, ValueError):
        year = None

    # Authors
    authors: list[str] = []
    for a in article.get("AuthorList", []) or []:
        name = " ".join(filter(None, [a.get("ForeName"), a.get("LastName")]))
        if name:
            authors.append(name)

    # DOI
    doi = ""
    for aid in rec.get("PubmedData", {}).get("ArticleIdList", []) or []:
        if getattr(aid, "attributes", {}).get("IdType") == "doi":
            doi = str(aid).lower()
            break

    # Study design
    pub_types = [str(t) for t in article.get("PublicationTypeList", []) or []]
    design = ""
    for pt in pub_types:
        if pt in _DESIGN_MAP:
            design = _DESIGN_MAP[pt]
            break

    language = (article.get("Language") or [""])[0] if article.get("Language") else ""

    return {
        "source": "PubMed",
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "pmid": pmid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "study_design": design,
        "language": language,
        "is_preprint": "Preprint" in pub_types,
    }


def search(
    keywords: str,
    start_date: str | None = None,
    end_date: str | None = None,
    languages: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_preprints: bool = True,
    max_results: int = 50,
    email: str = "paper-search-app@example.com",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Search PubMed and return normalized records."""
    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key

    query = _build_query(
        keywords, start_date, end_date, languages, study_designs, include_preprints
    )

    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
        ids = Entrez.read(handle).get("IdList", [])
        handle.close()
    except Exception as e:
        raise RuntimeError(f"PubMed esearch failed: {e}") from e

    if not ids:
        return []

    try:
        handle = Entrez.efetch(db="pubmed", id=",".join(ids), rettype="medline", retmode="xml")
        records = Entrez.read(handle).get("PubmedArticle", [])
        handle.close()
    except Exception as e:
        raise RuntimeError(f"PubMed efetch failed: {e}") from e

    return [_parse_record(r) for r in records]
