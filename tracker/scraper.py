"""
Scraper module: fetches job listings from career pages using Playwright
for JavaScript-rendered pages and BeautifulSoup4 for HTML parsing.
"""

import asyncio
import hashlib
import json
import math
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

JOB_LINK_HINTS = re.compile(
    r"(job|jobs|position|opening|vacan|requisition|reqid|stellen|karriere|"
    r"angebot|offer|personio|workdayjobs|greenhouse|lever|smartrecruiters|ashby|"
    r"posting|postings|pinpoint|pinpointhq)",
    re.IGNORECASE,
)

NON_JOB_TITLES = {
    "career",
    "careers",
    "job",
    "jobs",
    "job search",
    "all jobs",
    "view all jobs",
    "search jobs",
}

GENERIC_CTA_TITLES = {
    "view job",
    "apply",
    "apply now",
    "learn more",
    "details",
}


def _clean_text(value: str) -> str:
    """Return text with collapsed whitespace for stable matching/hashing."""
    return re.sub(r"\s+", " ", value or "").strip()


def _is_generic_cta_title(title: str) -> bool:
    """Return True when anchor text looks like a generic CTA, not a role title."""
    normalized = _clean_text(title).lower()
    if not normalized:
        return True

    if normalized in GENERIC_CTA_TITLES:
        return True

    # Some sites duplicate CTA text in nested spans, e.g. "View Job View Job".
    parts = normalized.split()
    if (
        len(parts) >= 2
        and len(set(parts)) == 2
        and parts.count("view") > 0
        and parts.count("job") > 0
        and parts.count("view") == parts.count("job")
    ):
        return True

    return False


def _derive_title_from_context(tag, fallback_title: str) -> str:
    """Derive a better title for generic CTA anchors from nearby row/list context."""
    if tag is None:
        return fallback_title

    container = tag.find_parent(["tr", "li", "article", "div"])
    if container is None:
        return fallback_title

    # For table rows, prefer first non-empty cell text.
    if container.name == "tr":
        for cell in container.find_all(["td", "th"], recursive=False):
            cell_text = _clean_text(cell.get_text(" ", strip=True))
            if cell_text and not _is_generic_cta_title(cell_text):
                return cell_text

    # Fallback: first text fragment in container that isn't a generic CTA.
    text = container.get_text(separator="\n", strip=True)
    if text:
        fragments = [frag.strip() for frag in text.split("\n") if frag.strip()]
        for frag in fragments:
            frag_clean = _clean_text(frag)
            if not _is_generic_cta_title(frag_clean) and len(frag_clean) >= 4:
                return frag_clean

    return fallback_title


def _is_probable_job_link(title: str, link: str, tag) -> bool:
    """Heuristic check to keep links that likely point to an individual job."""
    title_l = title.lower()
    if title_l in NON_JOB_TITLES:
        return False

    # Single-word links are often language/nav selectors (e.g. "German").
    if len(title.split()) == 1 and not re.search(r"(m/f/d|f/m/d|w/m/d)", title_l):
        return False

    if JOB_LINK_HINTS.search(link):
        return True

    classes = " ".join(tag.get("class", [])).lower() if tag else ""
    if JOB_LINK_HINTS.search(classes):
        return True

    parent = tag.parent
    if parent:
        parent_attrs = " ".join(parent.get("class", [])).lower()
        parent_id = (parent.get("id") or "").lower()
        if JOB_LINK_HINTS.search(parent_attrs) or JOB_LINK_HINTS.search(parent_id):
            return True

    data_id = (tag.get("data-id") or "").lower() if tag else ""
    if data_id and ("job" in data_id or "offer" in data_id):
        return True

    return False


def _extract_jobs_from_html(company: str, html: str, base_url: str) -> list[dict]:
    """
    Parse raw HTML and extract job listings.

    Uses job-link heuristics on anchor tags and returns unique entries with
    keys: title, link, hash.

    Parameters
    ----------
    company  : Company name (used in hashing).
    html     : Raw HTML string to parse.
    base_url : Fully-qualified page URL (must include scheme, e.g.
               ``https://...``) used to resolve relative hrefs via
               ``urllib.parse.urljoin``.
    """
    soup = BeautifulSoup(html, "html.parser")
    by_link: dict[str, dict] = {}

    for tag in soup.find_all("a", href=True):
        title = _clean_text(tag.get_text(separator=" ", strip=True))
        if not title or _is_generic_cta_title(title):
            # Try to find a title in child elements if the anchor itself is empty or generic
            nested_title = tag.find(["h1", "h2", "h3", "h4", "h5", "strong", "b", "p"])
            if nested_title and not _is_generic_cta_title(_clean_text(nested_title.get_text())):
                title = _clean_text(nested_title.get_text())
            else:
                # Fallback to deriving from context
                title = _derive_title_from_context(tag, title)

        if len(title) < 4 or len(title) > 500 or _is_generic_cta_title(title):
            continue

        href = _clean_text(tag["href"])
        # Allow any hash link that isn't just a bare '#'
        if not href or href == "#":
            continue

        link = urljoin(base_url, href)
        if not _is_probable_job_link(title, link, tag):
            # Log rejected links to help debug missing jobs (hidden behind debug flag if possible)
            # print(f"DEBUG: Rejected link for {company}: {link} (Title: {title})")
            continue

        existing = by_link.get(link)
        if existing and len(existing["title"]) >= len(title):
            continue

        by_link[link] = {
            "title": title,
            "link": link,
            "hash": _compute_hash(company, title, link),
        }

    return list(by_link.values())


def _compute_hash(company: str, title: str, link: str) -> str:
    """Return a SHA-256 hex digest for (company, title, link)."""
    raw = f"{company.lower()}|{title.strip().lower()}|{link.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_jobs_from_typesense_payload(company: str, payload: dict) -> list[dict]:
    """Extract jobs from a Typesense multi_search JSON payload."""
    results = payload.get("results") or []
    if not results:
        return []

    hits = results[0].get("hits") or []
    by_link: dict[str, dict] = {}

    for hit in hits:
        doc = hit.get("document") or {}
        title = _clean_text(str(doc.get("title") or ""))
        link = _clean_text(str(doc.get("application_url") or ""))
        if len(title) < 4 or not link:
            continue

        existing = by_link.get(link)
        if existing and len(existing["title"]) >= len(title):
            continue

        by_link[link] = {
            "title": title,
            "link": link,
            "hash": _compute_hash(company, title, link),
        }

    return list(by_link.values())


async def _fetch_jobs_typesense_if_available(
    company: str,
    url: str,
    timeout_ms: int = 30_000,
) -> Optional[list[dict]]:
    """
    For sites backed by my-job-shop Typesense search, fetch all job pages
    via the JSON API to avoid DOM pagination limits.
    """
    from playwright.async_api import async_playwright

    captured_endpoint: str | None = None
    captured_post_data: str | None = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            def _capture_request(req) -> None:
                nonlocal captured_endpoint, captured_post_data
                req_url = req.url
                if (
                    captured_endpoint is None
                    and "api.my-job-shop.com/api/typesense/multi_search" in req_url
                    and req.method.upper() == "POST"
                ):
                    captured_endpoint = req_url
                    captured_post_data = req.post_data

            page.on("request", _capture_request)

            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            await page.wait_for_timeout(1000)

            if not captured_endpoint or not captured_post_data:
                return None

            template = json.loads(captured_post_data)
            searches = template.get("searches")
            if not isinstance(searches, list) or not searches:
                return None

            template["searches"][0]["per_page"] = 100

            all_by_link: dict[str, dict] = {}
            found_total: int | None = None
            max_pages = 50

            for page_num in range(1, max_pages + 1):
                template["searches"][0]["page"] = page_num
                response = await page.request.post(
                    captured_endpoint,
                    data=json.dumps(template),
                    headers={"content-type": "application/json"},
                )
                if not response.ok:
                    break

                payload = await response.json()
                jobs = _extract_jobs_from_typesense_payload(company, payload)
                if not jobs:
                    break

                result0 = (payload.get("results") or [{}])[0]
                current_found = result0.get("found")
                if isinstance(current_found, int):
                    found_total = current_found

                for job in jobs:
                    existing = all_by_link.get(job["link"])
                    if existing and len(existing["title"]) >= len(job["title"]):
                        continue
                    all_by_link[job["link"]] = job

                if found_total is not None:
                    if len(all_by_link) >= found_total:
                        break
                    page_size = max(1, len(jobs))
                    expected_pages = math.ceil(found_total / page_size)
                    if page_num >= expected_pages:
                        break

            if all_by_link:
                return list(all_by_link.values())

            return None
        finally:
            await browser.close()


async def _fetch_jobs_crawl4ai(company: str, url: str, timeout_ms: int = 30_000) -> list[dict]:
    """
    Use Crawl4AI to load the page, handle pagination/load-more buttons,
    and extract jobs across multiple pages using the existing HTML heuristic parser.
    """
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, BrowserConfig

    session_id = f"session_{company}"
    all_by_link: dict[str, dict] = {}

    js_next = """
    (function() {
        console.log("Starting pagination click script...");
        const re = /(load more|show more|more jobs|more results|mehr laden|weitere|anzeigen)/i;
        let clicked = false;
        
        function forceClick(el) {
            if (!el) return false;
            console.log("Force clicking element:", el.tagName, el.className, el.innerText);
            el.click();
            el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
            el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            return true;
        }

        // 0. Try to find an "All" or "Alle" button first to bypass pagination
        const allTerms = ['all', 'alle', 'show all', 'alle anzeigen'];
        const allBtn = Array.from(document.querySelectorAll('button, a')).find(el => {
            const text = el.textContent.trim().toLowerCase();
            return allTerms.includes(text) && el.offsetParent !== null && (el.className.toLowerCase().includes('pagination') || el.parentElement.className.toLowerCase().includes('pagination'));
        });
        if (allBtn) {
            console.log("Found 'All' button, clicking to bypass pagination:", allBtn.textContent);
            if (forceClick(allBtn)) {
                clicked = true;
                // Return early so the scraper doesn't try to click "Next" immediately
                window.scrollBy(0, document.body.scrollHeight);
                return true;
            }
        }

        // 1. Try to find "Next" arrow based on typical sibling structure (like Aurora)
        const activeBtn = document.querySelector('button[class*="active"], a[class*="active"], .active, [aria-current="page"]');
        if (activeBtn) {
            let next = activeBtn.nextElementSibling;
            // Skip dots or separators if any
            while (next && (next.textContent.trim() === '...' || next.offsetHeight === 0)) {
                next = next.nextElementSibling;
            }
            if (next && (next.tagName === 'BUTTON' || next.tagName === 'A' || next.tagName === 'IMG')) {
                console.log("Found sibling next element:", next.tagName);
                if (forceClick(next)) clicked = true;
            }
        }

        // 2. Try common Next selectors with multilingual support
        if (!clicked) {
            const selectors = [
                'a.next', 'button.next', 
                '[aria-label*="Next" i]', '[aria-label*="next" i]',
                '[aria-label*="nächste" i]', '[aria-label*="weiter" i]', // German
                'li.next a', 'li.next button',
                '.pagination-next', '.next-page',
                'button[class*="Pagination_page_number"] ~ img:last-of-type',
                'div[class*="pagination"] img:last-of-type',
                'div[class*="Pagination"] img:last-of-type',
                'img[alt*="Next" i]', 'img[alt*="next" i]', 'img[alt*="nächste" i]'
            ];
            
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetParent !== null) {
                    console.log("Clicking selector match:", sel);
                    if (forceClick(el)) {
                        clicked = true;
                        break;
                    }
                }
            }
        }
        
        // 3. Text/Alt based search (Multilingual)
        if (!clicked) {
            const elements = Array.from(document.querySelectorAll('button, a, span, img'));
            const nextEl = elements.find(el => {
                const text = el.textContent.trim().toLowerCase();
                const alt = (el.getAttribute('alt') || '').toLowerCase();
                const nextTerms = ['next', '>', '»', 'next page', 'nächste', 'weiter', 'vorwärts', 'right arrow'];
                return (nextTerms.includes(text) || nextTerms.some(t => alt.includes(t))) && 
                       el.offsetParent !== null;
            });
            if (nextEl) {
                console.log("Clicking text/alt match:", nextEl.textContent || nextEl.getAttribute('alt'));
                if (forceClick(nextEl)) clicked = true;
            }
        }
        
        // 4. Fallback to "Load More"
        if (!clicked) {
            const elements = Array.from(document.querySelectorAll('button, a'));
            for (const el of elements) {
                const text = (el.innerText || el.textContent || '').trim();
                if (text && re.test(text) && el.offsetParent !== null) {
                    if (forceClick(el)) {
                        clicked = true;
                        break;
                    }
                }
            }
        }
        
        window.scrollBy(0, document.body.scrollHeight);
        return clicked;
    })();
    """

    browser_cfg = BrowserConfig(headless=True)
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # Load initial page
        config = CrawlerRunConfig(
            session_id=session_id,
            cache_mode=CacheMode.BYPASS,
            page_timeout=timeout_ms,
            delay_before_return_html=2.0,
            wait_until="networkidle"
        )
        result = await crawler.arun(url=url, config=config)
        
        if result.html:
            jobs = _extract_jobs_from_html(company, result.html, url)
            for j in jobs:
                all_by_link[j["link"]] = j

        # Try up to 25 pages for pagination
        for p in range(25):
            # Capture current page indicator before clicking
            js_capture = """
            (function() {
                const active = document.querySelector('button[class*="active"], a[class*="active"], .active, [aria-current="page"]');
                const range = document.querySelector('[data-automation-id="jobFoundCount"], [class*="pagination"], .page-indicator');
                window.lastPageIndicator = (active ? active.innerText : '') + (range ? range.innerText : '');
                if (!window.lastPageIndicator) window.lastPageIndicator = document.body.innerText.length;
                return window.lastPageIndicator;
            })();
            """
            
            next_config = CrawlerRunConfig(
                session_id=session_id,
                # Inject capture logic and track if a click happened
                js_code="window.clickHappened = false; window.lastPageIndicator = (function() { const active = document.querySelector('button[class*=\"active\"], a[class*=\"active\"], .active, [aria-current=\"page\"]'); const range = document.querySelector('[data-automation-id=\"jobFoundCount\"], [class*=\"pagination\"], .page-indicator, .pagination-range'); const val = (active ? active.innerText : '') + (range ? range.innerText : '') + window.location.hash; return val || document.body.innerText.length; })(); window.clickHappened = " + js_next,
                js_only=True,
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout_ms,
                # ONLY wait if a click actually happened
                wait_for="js:() => { if (!window.clickHappened) return true; const active = document.querySelector('button[class*=\"active\"], a[class*=\"active\"], .active, [aria-current=\"page\"]'); const range = document.querySelector('[data-automation-id=\"jobFoundCount\"], [class*=\"pagination\"], .page-indicator, .pagination-range'); const curr = (active ? active.innerText : '') + (range ? range.innerText : '') + window.location.hash; return (curr || document.body.innerText.length) !== window.lastPageIndicator; }",
                wait_for_timeout=timeout_ms
            )
            result = await crawler.arun(url=url, config=next_config)
            
            if not result.html:
                break
                
            jobs = _extract_jobs_from_html(company, result.html, url)
            added_new = False
            for j in jobs:
                if j["link"] not in all_by_link:
                    all_by_link[j["link"]] = j
                    added_new = True
            
            # If no new jobs were found, we might be at the end
            if not added_new:
                # One last short sleep and check to handle extremely slow renders
                await asyncio.sleep(2)
                final_html = result.html
                jobs = _extract_jobs_from_html(company, final_html, url)
                for j in jobs:
                    if j["link"] not in all_by_link:
                        all_by_link[j["link"]] = j
                        added_new = True
                
                if not added_new:
                    break

        await crawler.crawler_strategy.kill_session(session_id)

    return list(all_by_link.values())


async def _fetch_jobs_from_iframe_boards(
    company: str,
    url: str,
    timeout_ms: int = 30_000,
) -> Optional[list[dict]]:
    """
    Fetch jobs from embedded iframe job boards (e.g., Personio) when the
    top-level page itself does not contain listing anchors.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            # Give iframes more time to load and bypass overlays
            await page.wait_for_timeout(3000)

            all_by_link: dict[str, dict] = {}

            for frame in page.frames:
                if frame == page.main_frame:
                    continue

                frame_url = frame.url or ""
                if not frame_url or frame_url == "about:blank":
                    continue

                # Prioritize known ATS providers and job-like frame URLs.
                if not re.search(
                    r"(personio|jobs\.|jobboard|careers?|stellen|karriere|posting|pinpoint)",
                    frame_url,
                    re.IGNORECASE,
                ):
                    continue

                try:
                    frame_html = await frame.content()
                except Exception:
                    continue

                if not frame_html:
                    continue

                jobs = _extract_jobs_from_html(company, frame_html, frame_url)
                for job in jobs:
                    existing = all_by_link.get(job["link"])
                    if existing and len(existing["title"]) >= len(job["title"]):
                        continue
                    all_by_link[job["link"]] = job

            if all_by_link:
                return list(all_by_link.values())

            return None
        finally:
            await browser.close()


async def fetch_jobs(
    company: str,
    url: str,
    timeout_ms: int = 30_000,
    _html_override: Optional[str] = None,
) -> list[dict]:
    """
    Fetch and return the current job listings for *company* at *url*.

    Parameters
    ----------
    company      : Company name (used in hashing).
    url          : Career page URL.
    timeout_ms   : Browser navigation timeout in milliseconds.
    _html_override : If provided, parse this HTML instead of fetching.
                    Used for unit testing without a real browser.

    Returns
    -------
    List of job dicts with keys: title, link, hash.
    """
    if _html_override is not None:
        html = _html_override
        return _extract_jobs_from_html(company, html, url)
        
    jobs_from_api = await _fetch_jobs_typesense_if_available(company, url, timeout_ms)
    if jobs_from_api:
        return jobs_from_api

    jobs_from_iframes = await _fetch_jobs_from_iframe_boards(company, url, timeout_ms)
    if jobs_from_iframes:
        return jobs_from_iframes

    jobs_from_crawl4ai = await _fetch_jobs_crawl4ai(company, url, timeout_ms)
    return jobs_from_crawl4ai
