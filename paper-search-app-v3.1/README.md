# Auto-Review & Gap Analysis Platform

A Streamlit app that searches **PubMed**, **Europe PMC**, **Crossref**, **OpenAlex**, **Semantic Scholar**, **arXiv**, and **Springer Nature** in parallel, deduplicates results across sources, and surfaces medical research gaps along four axes — **volume**, **content**, **methodology**, and **temporal** — using **Google Gemini** for the LLM layer plus a heuristic fallback.

Built from the *Auto-Review & Gap Analysis* technical design (Phase 1 + Phase 2 + Phase 3, MVP scope).

---

## Features

- **Seven databases** queried in parallel — six are free, only Springer Nature requires a key.
- **Structured input UI**: keywords with boolean operators, date range, study design (RCT, cohort, case-control, systematic review, meta-analysis, observational, review), language, peer-reviewed-only or include-preprints.
- **Cross-source deduplication** by DOI first, then fuzzy-title matching for records without a DOI.
- **Results table** with title, journal, year, design, source, link, authors, abstract.
- **Gap analysis report** covering all four medical-gap types, grounded in the actual corpus stats. Falls back to a heuristic report when no Gemini key is set.
- **CSV / Excel / Markdown export** of results and the gap report.

---

## Local quickstart

```bash
git clone https://github.com/<you>/paper-search-app.git
cd paper-search-app

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit secrets.toml — paste your Gemini key and contact email

streamlit run app.py
```

Open <http://localhost:8501>.

---

## Deploying to Streamlit Cloud

1. Push this repo to GitHub.
2. Go to <https://share.streamlit.io>, click **New app**.
3. Pick the repo, branch `main`, main file `app.py`.
4. Click **Advanced settings → Secrets** and paste:

   ```toml
   GEMINI_API_KEY            = "..."
   NCBI_EMAIL                = "you@example.com"
   NCBI_API_KEY              = ""
   SPRINGER_API_KEY          = "..."   # required for Springer Nature
   SEMANTIC_SCHOLAR_API_KEY  = ""      # optional
   ```

5. Deploy.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit UI (app.py)                                          │
│   keywords · dates · designs · languages · sources · preprints  │
└─────────────────────────────────────────────────────────────────┘
                           │
   ┌────────┬────────┬─────┴──────┬────────┬──────────┬──────────┐
   ▼        ▼        ▼            ▼        ▼          ▼          ▼
 PubMed  Europe   Crossref     OpenAlex  Semantic   arXiv     Springer
         PMC                              Scholar              Nature
                                                              (Meta/OA)
   (free)  (free)  (free)      (free)    (free)    (free)    (key req)
   │        │        │            │        │          │          │
   └────────┴────────┴──────┬─────┴────────┴──────────┴──────────┘
                            ▼
                    search/dedup.py
                    (DOI → fuzzy title)
                            ▼
                    pandas DataFrame
                            ▼
                    analysis/gap.py
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
   heuristic stats                      Gemini gap report
   (always available)                   (when API key set)
```

### Gap-analysis prompt

The Gemini prompt is fed:

- **Corpus statistics** as JSON: counts by source, year, study design, journals; preprint count; recency buckets (last 2/5/10 years); longitudinal markers; population-keyword counts (pediatric, elderly, pregnancy, LMIC, female).
- **Up to 30 sample papers** (title — year — design — abstract excerpt).

It is instructed to return four sections — *Volume*, *Content*, *Methodology*, *Temporal* — and end with 3–5 concrete suggested research questions.

---

## Project layout

```
paper-search-app/
├── app.py                          Streamlit entry point
├── search/
│   ├── pubmed.py                   NCBI E-utilities (Biopython)
│   ├── europepmc.py                Europe PMC REST
│   ├── crossref.py                 Crossref REST
│   ├── openalex.py                 OpenAlex REST
│   ├── semanticscholar.py          Semantic Scholar Graph API
│   ├── arxiv.py                    arXiv Atom export
│   ├── springer.py                 Springer Meta + OA APIs
│   └── dedup.py                    DOI + fuzzy-title dedup
├── analysis/
│   └── gap.py                      Heuristics + Gemini prompt
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── requirements.txt
└── README.md
```

---

## Roadmap (out of MVP)

- Add **CORE** (free with key) — registration in flight.
- Add **Cochrane** via institutional Ovid access.
- Add **Scopus** / **Web of Science** for institutions with API keys.
- Persistent search history (SQLite).
- PRISMA-style flow diagram of dedup decisions.
- Citation-graph based gap detection (using OpenAlex `cited_by`).
