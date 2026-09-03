# Data Sources and Ingestion Strategies — Spectre - FantaMoneyball

`Spectre - FantaMoneyball` combines four disparate data sources to construct a comprehensive quantitative profile for every player in the league.

---

## Data Source Overview

| Source | Extracted Attributes | Ingestion Method | Historical Coverage |
|---|---|---|---|
| **Official League & Fantasy Source** | Historical ratings, Fantavotes, Goals, Assists, Penalties, Cards, Base Quotations, FVM | HTML Scraping (`BeautifulSoup`) + Excel Sheet Parsing | 11 Historical Seasons + Current Season |
| **Understat.com** | Expected Goals (xG), Expected Assists (xA), Non-penalty xG (npxG), Shots p90, Key Passes p90 | Internal REST API (`POST /main/getPlayersStats/`) | Recent 4 Seasons |
| **Transfermarkt.com** | Total days injured, count of injury events, medical diagnosis, severe injury indicators | Multithreaded Asynchronous Scraping (`ThreadPoolExecutor`) with local JSON cache | Recent 3 Seasons |
| **football-data.co.uk** | Match results, total shots, shots on target, home/away goal aggregates | Direct CSV Download | 11 Historical Seasons |

---

## Entity Resolution & Fuzzy Name Matching

Different platforms utilize contrasting naming conventions (e.g., diacritics, abbreviations, first-name initials, or nicknames). `Spectre - FantaMoneyball` employs a 4-tier normalization pipeline:

1. **Unicode Decomposition (NFD)**: Strips all diacritics and accented characters (e.g., `Kessié` -> `kessie`, `Laurienté` -> `lauriente`).
2. **Regex Initialization Stripping**: Eliminates trailing initials (e.g., `Martinez L.` -> `martinez`, `Paz N.` -> `paz`).
3. **Levenshtein Fuzzy Matching (`difflib.get_close_matches`)**: Similarity scoring with an acceptance threshold of 0.75 - 0.85.
4. **Manual Homonym Resolution Table (`MANUAL_FUZZY_MAP`)**: Explicit lookup dictionary to disambiguate siblings, identical surnames, or non-trivial transliterations (e.g., `Oyono A.` vs `Oyono J.`, `El Azzouzi A.` vs `El Azzouzi O.`).

---

## Scraping Resilience & Rate Limiting

- **Desktop User-Agent Headers**: Emulates modern desktop browser headers to prevent endpoint blocking.
- **Controlled Rate Limiting**: Inter-request delays (1.5s) on sequential endpoints.
- **Incremental Cache Persistence**: `tm_injuries_cache.json` is flushed to disk periodically (every 30 records) to allow resumption without redundant HTTP requests.
- **Automated Fallback Architecture**: If external match-data endpoints are unavailable, team offensive and defensive indices are derived dynamically by aggregating player-level goal data.
