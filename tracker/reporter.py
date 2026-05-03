"""
Reporter module: formats and prints job-tracking results to the console.
"""


def _truncate(text: str, max_len: int = 80) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def print_report(
    results: list[dict],
    *,
    show_closed: bool = True,
) -> None:
    """
    Print a human-readable summary of new and closed jobs.

    Parameters
    ----------
    results     : List of per-company result dicts produced by the main runner.
                  Each dict has keys:
                    company    - str
                    new_jobs   - list[dict]  (title, link, hash)
                    closed_jobs - list[dict] (title, link, hash)
                    error      - str | None
    show_closed : Whether to include the "Closed Jobs" section.
    """
    separator = "=" * 60

    total_new = sum(len(r["new_jobs"]) for r in results)
    total_closed = sum(len(r["closed_jobs"]) for r in results if not r.get("error"))

    print(separator)
    print("  DIY Job Tracker — Results")
    print(separator)

    for result in results:
        company = result["company"]
        new_jobs = result["new_jobs"]
        closed_jobs = result["closed_jobs"]
        error = result.get("error")

        print(f"\n[{company}]")

        if error:
            print(f"  ERROR: {error}")
            continue

        if new_jobs:
            print(f"  ✅ {len(new_jobs)} new job(s) found:")
            for job in new_jobs:
                title = _truncate(job["title"])
                link = job.get("link", "")
                if link:
                    print(f"    • {title}")
                    print(f"      {link}")
                else:
                    print(f"    • {title}")
        else:
            print("  No new jobs.")

        if show_closed and closed_jobs:
            print(f"  ❌ {len(closed_jobs)} job(s) no longer listed:")
            for job in closed_jobs:
                print(f"    • {_truncate(job['title'])}")

    print(f"\n{separator}")
    company_word = "company" if len(results) == 1 else "companies"
    print(f"  Summary: {total_new} new job(s) detected across {len(results)} {company_word}.")
    if show_closed:
        print(f"           {total_closed} job(s) appear to have closed.")
    print(separator)
