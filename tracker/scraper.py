"""
Scraper module: fetches job listings from career pages using Playwright
for JavaScript-rendered pages and BeautifulSoup4 for HTML parsing.
"""

import hashlib
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

JOB_KEYWORDS = re.compile(
    r"\b(engineer|developer|manager|analyst|designer|scientist|architect|"
    r"consultant|specialist|lead|director|intern|associate|coordinator|"
    r"administrator|recruiter|researcher|product|software|data|devops|"
    r"machine learning|cloud|security|qa|test|support)\b",
    re.IGNORECASE,
)


def _extract_jobs_from_html(company: str, html: str, base_url: str) -> list[dict]:
    """
    Parse raw HTML and extract job listings.

    Looks for <a> tags (or their parents) whose text contains common job-title
    keywords.  Returns a list of dicts with keys: title, link, hash.

    Parameters
    ----------
    company  : Company name (used in hashing).
    html     : Raw HTML string to parse.
    base_url : Fully-qualified page URL (must include scheme, e.g.
               ``https://...``) used to resolve relative hrefs via
               ``urllib.parse.urljoin``.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    jobs: list[dict] = []

    for tag in soup.find_all(["a", "h1", "h2", "h3", "h4", "li", "div", "span"]):
        text = tag.get_text(separator=" ", strip=True)
        if not JOB_KEYWORDS.search(text):
            continue
        if len(text) > 200 or len(text) < 4:
            continue

        link = ""
        if tag.name == "a" and tag.get("href"):
            href = tag["href"].strip()
            link = urljoin(base_url, href)
        else:
            anchor = tag.find("a", href=True)
            if anchor:
                href = anchor["href"].strip()
                link = urljoin(base_url, href)

        job_hash = _compute_hash(company, text, link)
        if job_hash in seen:
            continue
        seen.add(job_hash)

        jobs.append({"title": text, "link": link, "hash": job_hash})

    return jobs


def _compute_hash(company: str, title: str, link: str) -> str:
    """Return a SHA-256 hex digest for (company, title, link)."""
    raw = f"{company.lower()}|{title.strip().lower()}|{link.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _fetch_html_playwright(url: str, timeout_ms: int = 30_000) -> str:
    """
    Use a headless Chromium browser via Playwright to load the page and
    return the fully-rendered HTML.  Raises on any Playwright error so
    callers can skip archive updates on fetch failures.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            html = await page.content()
        finally:
            await browser.close()
    return html


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
    else:
        html = await _fetch_html_playwright(url, timeout_ms)

    if not html:
        return []

    return _extract_jobs_from_html(company, html, url)
