# JobTrack

A lightweight Python automation tool that monitors company career pages daily and reports new job listings by comparing the current page state with the last recorded state.

---

## Features

- **Layered scraping strategy** – tries a captured Typesense API first, then embedded iframe job boards, then fully rendered HTML via Playwright.
- **JavaScript-rendered pages** – uses Playwright (headless Chromium) so React/Vue/Angular job boards load fully before parsing.
- **Generic job extractor** – identifies job postings by scanning `<a>`, `<h*>`, `<li>`, `<div>`, and `<span>` tags for common role keywords (Engineer, Manager, Analyst, …).
- **Hash-based deduplication** – each job is uniquely identified by a SHA-256 hash of `(company + title + link)`, preventing false positives from minor text changes.
- **Persistent archive** – stores the last-seen state in `jobs_archive.json`; the file is updated only *after* the report is printed.
- **Console report** – prints new / closed jobs per company with a summary line.
- **Modular design** – scraper, database manager, and reporter are separate modules, making the tool easy to extend.

---

## Project Structure

```
DIY-Website-Tracker/
├── companies.json          # Your target companies and their career-page URLs
├── jobs_archive.json       # Auto-generated; stores last-seen job state
├── main.py                 # Entry point
├── pyproject.toml
├── tracker/
│   ├── __init__.py
│   ├── scraper.py          # Playwright + BeautifulSoup4 scraper
│   ├── database.py         # JSON persistence layer
│   └── reporter.py         # Console output formatter
└── tests/
    └── test_tracker.py     # Unit tests (30 tests, no network required)
```

---

## Quick Start

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install ".[dev]"
playwright install chromium
```

### 3. Configure target companies

Edit `companies.json`:

```json
{
  "Google": "https://careers.google.com/jobs/",
  "Microsoft": "https://careers.microsoft.com/us/en/search-results",
  "Stripe": "https://stripe.com/jobs/listing"
}
```

### 4. Run the tracker

```bash
python main.py
```

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--companies` | `companies.json` | Path to the companies config file |
| `--archive` | `jobs_archive.json` | Path to the persistent archive file |

```bash
python main.py --companies my_companies.json --archive my_archive.json
```

### 5. Schedule daily runs

**Linux / macOS (cron):**
```cron
0 8 * * * cd /path/to/DIY-Website-Tracker && source .venv/bin/activate && python main.py >> tracker.log 2>&1
```

**Windows (Task Scheduler):**  
Create a daily trigger that runs the following batch script from the project directory:
```batch
cd /d C:\path\to\DIY-Website-Tracker
.venv\Scripts\activate.bat
python main.py >> tracker.log 2>&1
```

---

## How It Works

1. For each company, `fetch_jobs()` tries the following scraping approaches in order:
   - **Captured Typesense API** – Playwright opens the page, listens for a `my-job-shop` / Typesense `multi_search` request, then replays that request page-by-page to collect the full result set from JSON.
   - **Embedded iframe job boards** – if the top-level page embeds a third-party board (for example Personio or Pinpoint-style job frames), the scraper inspects matching iframes and extracts jobs from the frame HTML.
   - **Rendered HTML fallback** – if no API or iframe jobs are found, Playwright loads the page in headless Chromium, waits for `networkidle`, scrolls, and clicks visible "load more" / "show more" style controls to reveal lazy-loaded listings.
2. BeautifulSoup4 parses the chosen HTML source and extracts likely job links.
   - Generic CTA text such as `View Job` or `Apply` is resolved from nearby row/list context when possible.
   - Relative links are normalized to absolute URLs.
   - Duplicate links are collapsed, keeping the longest title.
3. Each extracted entry is hashed as `SHA-256(company | title | link)`. A `description` is extracted from nearby listing context (sibling cells, paragraphs, or span text within the same container) and stored alongside the title and link, but is intentionally excluded from the hash so that description updates do not create false "new job" events.
4. The hashes are compared against those stored in `jobs_archive.json`:
    - **New jobs** → hashes in *current* but not in *archive*.
    - **Closed jobs** → hashes in *archive* but not in *current*.
5. The report is printed to the console.
6. The archive is updated with the current snapshot.

### Scraping Approaches in Detail

The scraper is intentionally layered so different career sites can be handled without writing company-specific code.

#### 1. Captured Typesense API

Some job sites render results from a backend search API instead of placing every job directly in the DOM. For these sites, Playwright captures the outgoing `POST` request to the Typesense `multi_search` endpoint and reuses the same payload to fetch all pages of results as structured JSON.

This is the most complete path because it avoids pagination and DOM visibility limits.

#### 2. Embedded iframe job boards

Some career pages embed a hosted ATS or job board inside an `<iframe>`. When that happens, the scraper checks non-main frames whose URLs look job-related and parses the frame contents directly instead of relying only on the outer page.

This helps with boards hosted by providers such as Personio, Pinpoint, and similar systems.

#### 3. Rendered HTML fallback

If no structured API or iframe jobs are found, the scraper falls back to generic rendered-page parsing:

- open the page in headless Chromium
- wait for the page to finish loading
- scroll and click visible "load more" / "show more" controls
- parse the final HTML with BeautifulSoup4

The HTML extractor uses heuristics to keep links that look like individual jobs and reject obvious navigation links such as generic career-home or "all jobs" pages.

---

## Running Tests

Make sure the virtual environment is activated, then run:

```bash
pytest tests/ -v
```

All 30 tests run entirely offline (no browser, no network) using an HTML override fixture.

---

## Requirements

- Python 3.9+
- `playwright` ≥ 1.40 (headless Chromium)
- `beautifulsoup4` ≥ 4.12
