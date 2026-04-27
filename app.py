"""Auto-Review & Gap Analysis Platform — Streamlit app.

Searches PubMed, Europe PMC, Crossref, and OpenAlex; deduplicates results;
runs a Gemini-powered medical gap analysis (volume, content, methodology,
temporal) plus a heuristic fallback.
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from analysis.gap import analyze_gaps
from search.crossref import search as search_crossref
from search.dedup import deduplicate
from search.europepmc import search as search_europepmc
from search.openalex import search as search_openalex
from search.pubmed import search as search_pubmed

st.set_page_config(
    page_title="Auto-Review & Gap Analysis",
    page_icon="🔬",
    layout="wide",
)

# ---------- Sidebar: configuration ---------------------------------------- #

st.sidebar.title("⚙️ Configuration")

# Gemini key — Streamlit secrets first, then sidebar input.
default_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
gemini_key = st.sidebar.text_input(
    "Gemini API key",
    value=default_key,
    type="password",
    help="Used for the LLM gap-analysis. Stored only in the current session.",
)

ncbi_email = st.sidebar.text_input(
    "Email for NCBI / Crossref",
    value=st.secrets.get("NCBI_EMAIL", "paper-search-app@example.com")
    if hasattr(st, "secrets") else "paper-search-app@example.com",
    help="NCBI requires a contact email; Crossref recommends one in the User-Agent.",
)

ncbi_api_key = st.sidebar.text_input(
    "NCBI API key (optional)",
    value=st.secrets.get("NCBI_API_KEY", "") if hasattr(st, "secrets") else "",
    type="password",
    help="Optional — increases PubMed rate limit from 3 to 10 requests/sec.",
)

st.sidebar.markdown("---")
st.sidebar.caption("All four databases are free. Add API keys in `.streamlit/secrets.toml` for deployment.")

# ---------- Main: header -------------------------------------------------- #

st.title("🔬 Auto-Review & Gap Analysis Platform")
st.caption("Search PubMed · Europe PMC · Crossref · OpenAlex — then surface volume, content, methodology, and temporal gaps.")

# ---------- Search form --------------------------------------------------- #

with st.form("search_form"):
    keywords = st.text_area(
        "Keywords / MeSH terms (boolean operators allowed: AND, OR, NOT)",
        placeholder='e.g.  ("type 2 diabetes" AND ("mediterranean diet" OR "DASH diet")) NOT review',
        height=80,
    )

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start date", value=date.today() - timedelta(days=365 * 5), max_value=date.today()
        )
    with col2:
        end_date = st.date_input("End date", value=date.today(), max_value=date.today())

    col3, col4 = st.columns(2)
    with col3:
        study_designs = st.multiselect(
            "Study design",
            ["RCT", "Cohort", "Case-Control", "Systematic Review", "Meta-Analysis", "Observational", "Review"],
            default=[],
            help="Leave empty to include all designs.",
        )
    with col4:
        languages = st.multiselect(
            "Language",
            ["English", "French", "Spanish", "German", "Chinese", "Japanese", "Portuguese", "Italian"],
            default=["English"],
        )

    col5, col6 = st.columns(2)
    with col5:
        sources = st.multiselect(
            "Databases to query",
            ["PubMed", "Europe PMC", "Crossref", "OpenAlex"],
            default=["PubMed", "Europe PMC", "Crossref", "OpenAlex"],
        )
    with col6:
        include_preprints = st.toggle(
            "Include preprints", value=False,
            help="Off = peer-reviewed only.",
        )

    max_per_source = st.slider(
        "Max results per source", min_value=10, max_value=200, value=50, step=10
    )

    submitted = st.form_submit_button("🔎 Search", type="primary", use_container_width=True)


# ---------- Search execution --------------------------------------------- #

@st.cache_data(show_spinner=False, ttl=3600)
def _run_search(
    keywords: str,
    start_iso: str,
    end_iso: str,
    languages: tuple[str, ...],
    designs: tuple[str, ...],
    sources: tuple[str, ...],
    include_preprints: bool,
    max_per_source: int,
    ncbi_email: str,
    ncbi_api_key: str,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    raw: list[dict] = []
    errors: dict[str, str] = {}
    common = {
        "keywords": keywords,
        "start_date": start_iso,
        "end_date": end_iso,
        "languages": list(languages) if languages else None,
        "study_designs": list(designs) if designs else None,
        "include_preprints": include_preprints,
        "max_results": max_per_source,
    }

    if "PubMed" in sources:
        try:
            raw.extend(search_pubmed(**common, email=ncbi_email, api_key=ncbi_api_key or None))
        except Exception as e:  # noqa: BLE001
            errors["PubMed"] = str(e)
    if "Europe PMC" in sources:
        try:
            raw.extend(search_europepmc(**common))
        except Exception as e:  # noqa: BLE001
            errors["Europe PMC"] = str(e)
    if "Crossref" in sources:
        try:
            raw.extend(search_crossref(**common))
        except Exception as e:  # noqa: BLE001
            errors["Crossref"] = str(e)
    if "OpenAlex" in sources:
        try:
            raw.extend(search_openalex(**common))
        except Exception as e:  # noqa: BLE001
            errors["OpenAlex"] = str(e)

    deduped = deduplicate(raw)
    return raw, deduped, errors


if submitted:
    if not keywords.strip():
        st.error("Please enter at least one keyword or MeSH term.")
        st.stop()
    if start_date > end_date:
        st.error("Start date must be before end date.")
        st.stop()
    if not sources:
        st.error("Pick at least one database.")
        st.stop()

    with st.spinner(f"Querying {len(sources)} database(s)…"):
        raw, deduped, errors = _run_search(
            keywords=keywords,
            start_iso=start_date.isoformat(),
            end_iso=end_date.isoformat(),
            languages=tuple(languages),
            designs=tuple(study_designs),
            sources=tuple(sources),
            include_preprints=include_preprints,
            max_per_source=max_per_source,
            ncbi_email=ncbi_email,
            ncbi_api_key=ncbi_api_key,
        )

    st.session_state["raw"] = raw
    st.session_state["deduped"] = deduped
    st.session_state["errors"] = errors
    st.session_state["last_query"] = keywords


# ---------- Results display ---------------------------------------------- #

if "deduped" in st.session_state:
    raw = st.session_state["raw"]
    deduped = st.session_state["deduped"]
    errors = st.session_state.get("errors", {})

    if errors:
        with st.expander(f"⚠️ {len(errors)} source(s) had errors", expanded=False):
            for src, msg in errors.items():
                st.warning(f"**{src}** — {msg}")

    a, b, c, d = st.columns(4)
    a.metric("Raw hits", len(raw))
    b.metric("After dedup", len(deduped))
    c.metric("With abstract", sum(1 for r in deduped if (r.get("abstract") or "").strip()))
    d.metric("Preprints", sum(1 for r in deduped if r.get("is_preprint")))

    if not deduped:
        st.info("No results. Try broadening keywords, removing filters, or expanding the date range.")
        st.stop()

    tabs = st.tabs(["📋 Results", "📊 Gap Analysis", "📤 Export"])

    # ---- Results tab ----
    with tabs[0]:
        df = pd.DataFrame([
            {
                "Title": r.get("title", ""),
                "Year": r.get("year"),
                "Journal": r.get("journal", ""),
                "Design": r.get("study_design", ""),
                "Source": r.get("source", ""),
                "DOI": r.get("doi", ""),
                "Link": r.get("url", ""),
                "Authors": ", ".join((r.get("authors") or [])[:5]),
                "Preprint": r.get("is_preprint", False),
                "Abstract": r.get("abstract", ""),
            }
            for r in deduped
        ])
        st.dataframe(
            df.drop(columns=["Abstract"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link"),
                "Year": st.column_config.NumberColumn(format="%d"),
            },
        )
        with st.expander("📖 Browse abstracts"):
            for r in deduped[:50]:
                st.markdown(
                    f"**[{r.get('title','(untitled)')}]({r.get('url','')})** — "
                    f"*{r.get('journal','')}*, {r.get('year','?')} · {r.get('source','')}"
                )
                st.caption(", ".join((r.get("authors") or [])[:8]))
                st.write(r.get("abstract") or "_No abstract available._")
                st.markdown("---")

    # ---- Gap analysis tab ----
    with tabs[1]:
        if st.button("🧠 Run gap analysis", type="primary"):
            with st.spinner("Computing heuristics + querying Gemini…"):
                report = analyze_gaps(
                    deduped,
                    user_query=st.session_state.get("last_query", ""),
                    api_key=gemini_key or None,
                )
            st.session_state["gap_report"] = report

        report = st.session_state.get("gap_report")
        if report:
            stats = report["stats"]

            st.subheader("Corpus statistics")
            sa, sb, sc = st.columns(3)
            sa.metric("Papers", stats["n_total"])
            sb.metric("Last 5 years", stats["last_5y"])
            sc.metric("Longitudinal", stats["longitudinal"])

            cc1, cc2 = st.columns(2)
            with cc1:
                st.caption("By study design")
                st.bar_chart(pd.Series(stats["by_design"]).sort_values(ascending=False))
            with cc2:
                st.caption("By year")
                if stats["by_year"]:
                    st.bar_chart(pd.Series(stats["by_year"]))

            st.subheader("Gemini gap report")
            if report.get("llm"):
                st.markdown(report["llm"])
            elif report.get("llm_error"):
                st.error(f"Gemini call failed: {report['llm_error']}")
                st.markdown(report["heuristic"])
            else:
                st.info("No Gemini API key set — showing heuristic report only.")
                st.markdown(report["heuristic"])

            with st.expander("Heuristic report (always available)"):
                st.markdown(report["heuristic"])

    # ---- Export tab ----
    with tabs[2]:
        df_full = pd.DataFrame(deduped)
        csv = df_full.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download CSV (all fields)",
            data=csv,
            file_name="paper_search_results.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # Excel
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            df_full.to_excel(xw, index=False, sheet_name="results")
        st.download_button(
            "⬇️ Download Excel",
            data=buf.getvalue(),
            file_name="paper_search_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if "gap_report" in st.session_state:
            gr = st.session_state["gap_report"]
            md = (gr.get("llm") or "") + "\n\n---\n\n" + gr.get("heuristic", "")
            st.download_button(
                "⬇️ Download gap report (Markdown)",
                data=md.encode("utf-8"),
                file_name="gap_report.md",
                mime="text/markdown",
                use_container_width=True,
            )

else:
    st.info("👆 Set your search above and hit **Search**.")
