# Copilot Instructions

## Environment and commands

Use Python 3.9+ in a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]"
playwright install chromium
```

### Tests

Run the full offline suite from the repository root:

```bash
pytest tests/ -v
```

Run a single test with standard pytest node selection:

```bash
pytest tests/test_tracker.py::TestExtractJobsFromHtml::test_prefers_longer_title_for_same_link -v
```

## High-level architecture

The project is a small pipeline with three main stages coordinated by `main.py`:

1. `main.py` loads `companies.json`, iterates company-by-company, calls `tracker.scraper.fetch_jobs()`, compares the current snapshot against the archive with `DatabaseManager`, prints one consolidated report, and only then persists updates.
2. `tracker/scraper.py` is the core of the app. `fetch_jobs()` uses a layered strategy in this order:
   - capture and replay a Typesense `multi_search` request when the site uses `my-job-shop`
   - inspect embedded iframe job boards and parse the frame HTML
   - fall back to a generic rendered-page crawl with Crawl4AI plus heuristic extraction
3. `tracker/database.py` stores state in `jobs_archive.json`, keyed by company and then by job hash, and provides the `find_new_jobs()` / `find_closed_jobs()` comparisons.
4. `tracker/reporter.py` formats the per-company result objects that `main.py` builds. The reporter expects dicts with `company`, `new_jobs`, `closed_jobs`, and optional `error`.

## Key conventions in this repository

- Preserve the `print report first, update archive after` flow. `main.run()` intentionally delays `update_company()` calls until every company result has been reported.
- Keep the scraper strategy order intact unless there is a strong reason to change it: Typesense API first, iframe boards second, generic rendered HTML last.
- Job identity is hash-based. `_compute_hash()` lowercases and trims `company`, `title`, and `link`, then hashes `company|title|link` with SHA-256. Changes that affect hashing will change archive compatibility.
- HTML extraction deduplicates by normalized final link and keeps the longest title seen for that link. Generic CTA text such as `View Job` or `Apply` should be resolved from nearby context instead of being kept as the title.
- `companies.json` is expected to be a JSON object mapping company names to career-page URLs. `load_companies()` exits on missing files, invalid JSON, or the wrong top-level shape.
- The archive format is:

```json
{
  "CompanyName": {
    "<hash>": {
      "title": "...",
      "link": "...",
      "description": "...",
      "hash": "..."
    }
  }
}
```

- Tests are designed to stay offline. When adding scraper coverage, prefer `fetch_jobs(..., _html_override=...)` or direct HTML parsing helpers instead of real browser/network calls.

## Playwright MCP guidance

Use a Playwright MCP server for debugging real career pages when a scraping failure depends on rendered DOM state, iframe contents, pagination behavior, lazy loading, or intercepted network traffic. That is most useful when reproducing issues in the Typesense capture path, iframe-board path, or generic rendered-page fallback in `tracker/scraper.py`.

Do not use Playwright MCP for normal test coverage in this repository. Keep automated tests offline and deterministic by using `_html_override` or direct parser/database/reporter unit tests.
