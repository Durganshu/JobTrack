"""
main.py – Entry point for the DIY Job Tracker.

Usage:
    python main.py [--companies companies.json] [--archive jobs_archive.json]

Workflow per company:
1. Fetch current jobs from the career page (Playwright + BeautifulSoup).
2. Load archived jobs from jobs_archive.json.
3. Compute new / closed jobs.
4. Print a consolidated report.
5. Update the archive AFTER the report is printed.
"""

import argparse
import asyncio
import json
import os
import sys

from tracker.database import DatabaseManager
from tracker.reporter import print_report
from tracker.scraper import fetch_jobs


def load_companies(path: str) -> dict[str, str]:
    """Load company → URL mapping from a JSON config file."""
    if not os.path.exists(path):
        print(f"ERROR: companies config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"ERROR: companies config file is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
    if not isinstance(data, dict):
        print("ERROR: companies.json must be a JSON object mapping company names to URLs.",
              file=sys.stderr)
        sys.exit(1)
    return data


async def run(companies_path: str, archive_path: str) -> None:
    companies = load_companies(companies_path)
    db = DatabaseManager(archive_path)

    results = []
    # We collect updates and only apply them AFTER all reports are generated
    # (requirement 4.4 / implementation instruction 4).
    pending_updates: list[tuple[str, list[dict]]] = []

    for company, url in companies.items():
        print(f"Checking {company} at {url} …")
        error: str | None = None
        new_jobs: list[dict] = []
        closed_jobs: list[dict] = []
        current_jobs: list[dict] = []

        try:
            current_jobs = await fetch_jobs(company, url)
            archived = db.get_archived_jobs(company)
            new_jobs = DatabaseManager.find_new_jobs(current_jobs, archived)
            closed_jobs = DatabaseManager.find_closed_jobs(current_jobs, archived)
            pending_updates.append((company, current_jobs))
        except Exception as exc:
            error = str(exc)

        results.append(
            {
                "company": company,
                "new_jobs": new_jobs,
                "closed_jobs": closed_jobs,
                "error": error,
            }
        )

    # Print the report BEFORE updating the archive (per spec §6.4).
    print_report(results)

    # Now update the archive.
    for company, jobs in pending_updates:
        db.update_company(company, jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description="DIY Job Tracker")
    parser.add_argument(
        "--companies",
        default="companies.json",
        help="Path to companies config JSON (default: companies.json)",
    )
    parser.add_argument(
        "--archive",
        default="jobs_archive.json",
        help="Path to jobs archive JSON (default: jobs_archive.json)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.companies, args.archive))


if __name__ == "__main__":
    main()
