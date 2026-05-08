"""Gap analysis: heuristic stats + Gemini-powered narrative report.

Covers four kinds of gap:
  - Volume:       small absolute counts, sparse subtopics
  - Content:      missing populations / outcomes / settings
  - Methodology:  lack of RCTs, systematic reviews, meta-analyses, longitudinal
  - Temporal:     no recent work, no historical baseline, sparse decade(s)
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

try:
    import google.generativeai as genai
    _HAS_GEMINI = True
except Exception:  # noqa: BLE001
    _HAS_GEMINI = False


# ---------- Heuristics ---------------------------------------------------- #

def heuristic_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute counts that drive both the heuristic report and the LLM context."""
    n = len(records)
    by_source = Counter(r.get("source", "") for r in records)
    by_year: Counter = Counter()
    for r in records:
        y = r.get("year")
        if isinstance(y, int):
            by_year[y] += 1

    by_design = Counter((r.get("study_design") or "Unspecified") for r in records)
    by_journal = Counter((r.get("journal") or "Unknown") for r in records)
    preprints = sum(1 for r in records if r.get("is_preprint"))
    with_abstract = sum(1 for r in records if (r.get("abstract") or "").strip())

    # Temporal gap markers
    this_year = datetime.utcnow().year
    recent = sum(1 for y in by_year.elements() if y >= this_year - 2)
    last_5 = sum(1 for y in by_year.elements() if y >= this_year - 5)
    last_10 = sum(1 for y in by_year.elements() if y >= this_year - 10)
    longitudinal_terms = ("longitudinal", "long-term", "follow-up", "follow up", "5-year", "10-year")
    longitudinal = sum(
        1
        for r in records
        if any(t in (r.get("abstract") or r.get("title") or "").lower() for t in longitudinal_terms)
    )

    populations = {
        "pediatric": ("pediatric", "paediatric", "children", "child", "infant", "neonate", "adolescent"),
        "elderly": ("elderly", "geriatric", "older adult", "aged"),
        "pregnancy": ("pregnant", "pregnancy", "maternal"),
        "lmic": ("low-income", "middle-income", "lmic", "low- and middle-income", "developing countr"),
        "female": ("women", "female", "women's"),
    }
    pop_counts: Counter = Counter()
    for r in records:
        blob = ((r.get("title") or "") + " " + (r.get("abstract") or "")).lower()
        for label, kws in populations.items():
            if any(k in blob for k in kws):
                pop_counts[label] += 1

    return {
        "n_total": n,
        "by_source": dict(by_source),
        "by_year": dict(sorted(by_year.items())),
        "by_design": dict(by_design),
        "top_journals": dict(by_journal.most_common(10)),
        "preprints": preprints,
        "with_abstract": with_abstract,
        "recent_2y": recent,
        "last_5y": last_5,
        "last_10y": last_10,
        "longitudinal": longitudinal,
        "populations": dict(pop_counts),
    }


def heuristic_report(stats: dict[str, Any]) -> str:
    """A short markdown report from heuristics only — used when no Gemini key."""
    n = stats["n_total"]
    if n == 0:
        return "_No results — cannot compute a gap report._"

    lines: list[str] = ["### Heuristic Gap Report", "", f"**Total deduplicated papers:** {n}", ""]

    # Volume
    lines.append("**Volume**")
    designs = stats["by_design"]
    sparse = [d for d, c in designs.items() if c < max(3, int(n * 0.05))]
    if sparse:
        lines.append(f"- Sparse study designs (<5% of corpus): {', '.join(sparse)}.")
    else:
        lines.append("- No obvious volume gap by study design at this query scope.")
    lines.append("")

    # Methodology
    lines.append("**Methodology**")
    rct = designs.get("RCT", 0)
    sr = designs.get("Systematic Review", 0)
    ma = designs.get("Meta-Analysis", 0)
    lines.append(f"- RCTs: {rct} | Systematic reviews: {sr} | Meta-analyses: {ma}.")
    if rct < max(5, int(n * 0.1)):
        lines.append("- Few RCTs relative to corpus — methodological gap likely.")
    if (sr + ma) == 0:
        lines.append("- No systematic reviews or meta-analyses found — synthesis gap.")
    lines.append(f"- Long-term/follow-up papers: {stats['longitudinal']}.")
    if stats["longitudinal"] < max(3, int(n * 0.05)):
        lines.append("- Sparse longitudinal follow-up — temporal-methodology gap.")
    lines.append("")

    # Temporal
    lines.append("**Temporal**")
    lines.append(
        f"- Last 2 years: {stats['recent_2y']} | last 5 years: {stats['last_5y']} | "
        f"last 10 years: {stats['last_10y']}."
    )
    if stats["recent_2y"] == 0:
        lines.append("- No work in the last 2 years — possible recency gap.")
    if stats["last_5y"] < 3:
        lines.append("- <3 papers in the last 5 years — recency/momentum gap.")
    lines.append("")

    # Content (populations)
    lines.append("**Content / Populations**")
    pops = stats["populations"]
    for label in ("pediatric", "elderly", "pregnancy", "lmic", "female"):
        c = pops.get(label, 0)
        if c < max(2, int(n * 0.03)):
            lines.append(f"- {label.capitalize()}: only {c} mentions — possible content gap.")
    lines.append("")
    lines.append(f"**Top journals:** {', '.join(list(stats['top_journals'].keys())[:5]) or 'n/a'}.")
    return "\n".join(lines)


# ---------- Gemini -------------------------------------------------------- #

_PROMPT = """You are an evidence-synthesis analyst. Using the structured corpus
statistics and a sample of titles+abstracts below, produce a concise GAP REPORT
covering FOUR types of medical research gap:

  1. VOLUME GAP        — subtopics or designs with too few papers.
  2. CONTENT GAP       — populations, outcomes, settings, or comparators that
                          are under-represented (e.g. pediatrics, LMIC, women,
                          long-term outcomes).
  3. METHODOLOGY GAP   — missing RCTs, systematic reviews, meta-analyses,
                          longitudinal data, registries.
  4. TEMPORAL GAP      — missing recent work, missing historical baseline,
                          uneven decade coverage.

Rules:
- Ground every claim in the data provided. Do not invent papers.
- Cite specific counts when relevant ("only 4 of 87 papers cover pediatrics").
- End with a "Suggested research questions" section: 3–5 concrete questions
  that would close the most actionable gaps.
- Use markdown headings (##) for each of the four gap types.
- ≤ 600 words.

CORPUS STATS (JSON):
{stats_json}

SAMPLE OF UP TO 30 PAPERS (title — year — design — abstract excerpt):
{samples}

USER QUERY: {query}
"""


def _format_samples(records: list[dict[str, Any]], k: int = 30) -> str:
    rows: list[str] = []
    for r in records[:k]:
        abstract = (r.get("abstract") or "").strip().replace("\n", " ")
        if len(abstract) > 400:
            abstract = abstract[:400] + "…"
        rows.append(
            f"- {r.get('title','')} — {r.get('year','?')} — "
            f"{r.get('study_design') or 'Unspecified'} — {abstract}"
        )
    return "\n".join(rows) if rows else "(no abstracts)"


def analyze_gaps(
    records: list[dict[str, Any]],
    user_query: str,
    api_key: str | None = None,
    model_name: str = "gemini-1.5-flash",
) -> dict[str, Any]:
    """Return a dict with `stats`, `heuristic`, and (if key provided) `llm` keys."""
    stats = heuristic_summary(records)
    heur = heuristic_report(stats)
    out: dict[str, Any] = {"stats": stats, "heuristic": heur, "llm": None, "llm_error": None}

    if not api_key or not _HAS_GEMINI or not records:
        return out

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = _PROMPT.format(
            stats_json=json.dumps(stats, default=str),
            samples=_format_samples(records),
            query=user_query or "(unspecified)",
        )
        resp = model.generate_content(prompt)
        out["llm"] = (resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        out["llm_error"] = str(e)

    return out
