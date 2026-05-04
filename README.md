# JobTrack

A lightweight Python automation tool that monitors company career pages daily and reports new job listings by comparing the current page state with the last recorded state.

---

## Features

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

1. For each company, Playwright launches a headless browser, navigates to the career page, and waits for the network to go idle (so JavaScript-rendered content is fully loaded).
2. BeautifulSoup4 parses the rendered HTML and extracts elements whose text matches common job-title keywords.
3. Each extracted entry is hashed as `SHA-256(company | title | link)`.
4. The hashes are compared against those stored in `jobs_archive.json`:
   - **New jobs** → hashes in *current* but not in *archive*.
   - **Closed jobs** → hashes in *archive* but not in *current*.
5. The report is printed to the console.
6. The archive is updated with the current snapshot.

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
