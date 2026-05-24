"""
Unit tests for the DIY Job Tracker.

These tests exercise the core logic (hashing, parsing, DB operations,
comparison, and reporting) without requiring a live browser or network.
"""

import json
import os
import sys
import tempfile

import pytest

# Ensure the repo root is on the path when running from any directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.database import DatabaseManager
from tracker.reporter import print_report
from tracker.scraper import (
    _compute_hash,
    _extract_jobs_from_html,
    _extract_jobs_from_typesense_payload,
    fetch_jobs,
)


# ---------------------------------------------------------------------------
# scraper – _compute_hash
# ---------------------------------------------------------------------------


class TestComputeHash:
    def test_same_inputs_give_same_hash(self):
        h1 = _compute_hash("ACME", "Software Engineer", "https://acme.com/jobs/1")
        h2 = _compute_hash("ACME", "Software Engineer", "https://acme.com/jobs/1")
        assert h1 == h2

    def test_different_titles_give_different_hashes(self):
        h1 = _compute_hash("ACME", "Software Engineer", "https://acme.com/jobs/1")
        h2 = _compute_hash("ACME", "Data Analyst", "https://acme.com/jobs/1")
        assert h1 != h2

    def test_case_insensitive(self):
        h1 = _compute_hash("ACME", "Software Engineer", "https://acme.com/jobs/1")
        h2 = _compute_hash("acme", "software engineer", "HTTPS://ACME.COM/JOBS/1")
        assert h1 == h2

    def test_hash_is_64_hex_chars(self):
        h = _compute_hash("X", "Engineer", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# scraper – _extract_jobs_from_html
# ---------------------------------------------------------------------------


SAMPLE_HTML = """
<html>
<body>
  <ul>
    <li><a href="/jobs/1">Senior Software Engineer</a></li>
    <li><a href="/jobs/2">Product Manager</a></li>
    <li><a href="/jobs/3">Data Analyst</a></li>
    <li>Company Blog Post about our culture</li>
  </ul>
  <p>No relevant text here</p>
</body>
</html>
"""


class TestExtractJobsFromHtml:
    def test_extracts_job_links(self):
        jobs = _extract_jobs_from_html("ACME", SAMPLE_HTML, "https://acme.com")
        titles = [j["title"] for j in jobs]
        assert any("Engineer" in t for t in titles)
        assert any("Manager" in t for t in titles)
        assert any("Analyst" in t for t in titles)

    def test_non_job_text_excluded(self):
        jobs = _extract_jobs_from_html("ACME", SAMPLE_HTML, "https://acme.com")
        titles = [j["title"] for j in jobs]
        assert not any("Blog Post" in t for t in titles)

    def test_absolute_links_preserved(self):
        html = '<a href="https://acme.com/jobs/99">Cloud Architect</a>'
        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")
        assert any(j["link"] == "https://acme.com/jobs/99" for j in jobs)

    def test_relative_links_resolved(self):
        html = '<a href="/jobs/42">DevOps Engineer</a>'
        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")
        assert any(j["link"] == "https://acme.com/jobs/42" for j in jobs)

    def test_no_duplicates(self):
        # Same link appears twice in the HTML.
        html = """
        <a href="/jobs/1">Software Engineer</a>
        <a href="/jobs/1">Software Engineer</a>
        """
        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")
        hashes = [j["hash"] for j in jobs]
        assert len(hashes) == len(set(hashes))

    def test_each_job_has_hash(self):
        jobs = _extract_jobs_from_html("ACME", SAMPLE_HTML, "https://acme.com")
        for job in jobs:
            assert "hash" in job
            assert len(job["hash"]) == 64
            assert "description" in job

    def test_empty_html_returns_empty(self):
        jobs = _extract_jobs_from_html("ACME", "", "https://acme.com")
        assert jobs == []

    def test_non_job_navigation_link_excluded(self):
        html = '<a href="/careers">Careers</a>'
        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")
        assert jobs == []

    def test_prefers_longer_title_for_same_link(self):
        html = """
        <a href="/jobs/42">Data Analyst</a>
        <a href="/jobs/42">Senior Data Analyst (m/f/d) Berlin</a>
        """
        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Senior Data Analyst (m/f/d) Berlin"


    def test_extracts_pinpointhq_table_jobs_with_generic_cta_text(self):
        html = """
        <table>
          <tr>
            <td>Software Engineer</td>
            <td>Oxford</td>
            <td><a href="https://auroraer.pinpointhq.com/en/postings/abc">View Job</a></td>
          </tr>
          <tr>
            <td>Energy Modelling Analyst</td>
            <td>Vila Mariana</td>
            <td><a href="https://auroraer.pinpointhq.com/en/postings/def">View Job View Job</a></td>
          </tr>
        </table>
        """

        jobs = _extract_jobs_from_html("aurora", html, "https://auroraer.com/careers/join-us")

        assert len(jobs) == 2
        titles = sorted(job["title"] for job in jobs)
        links = sorted(job["link"] for job in jobs)

        assert titles == ["Energy Modelling Analyst", "Software Engineer"]
        assert links == [
            "https://auroraer.pinpointhq.com/en/postings/abc",
            "https://auroraer.pinpointhq.com/en/postings/def",
        ]
        descriptions = {job["title"]: job["description"] for job in jobs}
        assert descriptions == {
            "Energy Modelling Analyst": "Vila Mariana",
            "Software Engineer": "Oxford",
        }

    def test_extracts_description_from_job_card_context(self):
        html = """
        <article class="job-card">
          <a href="/jobs/7">Backend Engineer</a>
          <p>Build APIs for the tracker platform.</p>
          <span>Remote in Germany</span>
        </article>
        """

        jobs = _extract_jobs_from_html("ACME", html, "https://acme.com")

        assert len(jobs) == 1
        assert jobs[0]["description"] == "Build APIs for the tracker platform. | Remote in Germany"


class TestExtractJobsFromTypesensePayload:
    def test_extracts_description_when_available(self):
        payload = {
            "results": [
                {
                    "hits": [
                        {
                            "document": {
                                "title": "Platform Engineer",
                                "application_url": "https://acme.com/jobs/88",
                                "description": "<p>Own the deployment pipeline.</p>",
                            }
                        }
                    ]
                }
            ]
        }

        jobs = _extract_jobs_from_typesense_payload("ACME", payload)

        assert len(jobs) == 1
        assert jobs[0]["description"] == "Own the deployment pipeline."


# ---------------------------------------------------------------------------
# scraper – fetch_jobs (async, using _html_override)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_jobs_with_html_override():
    jobs = await fetch_jobs("ACME", "https://acme.com", _html_override=SAMPLE_HTML)
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    for job in jobs:
        assert "title" in job
        assert "description" in job
        assert "hash" in job


@pytest.mark.asyncio
async def test_fetch_jobs_empty_html_override():
    jobs = await fetch_jobs("ACME", "https://acme.com", _html_override="")
    assert jobs == []


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_archive(tmp_path):
    return str(tmp_path / "jobs_archive.json")


class TestDatabaseManager:
    def test_starts_empty_when_no_file(self, temp_archive):
        db = DatabaseManager(temp_archive)
        assert db.get_archived_jobs("ACME") == {}

    def test_update_and_retrieve(self, temp_archive):
        db = DatabaseManager(temp_archive)
        jobs = [
            {"title": "Engineer", "link": "https://x.com/1", "description": "Backend role", "hash": "abc"},
            {"title": "Analyst", "link": "https://x.com/2", "description": "Data team", "hash": "def"},
        ]
        db.update_company("ACME", jobs)
        archived = db.get_archived_jobs("ACME")
        assert "abc" in archived
        assert "def" in archived
        assert archived["abc"]["description"] == "Backend role"

    def test_persists_to_disk(self, temp_archive):
        db = DatabaseManager(temp_archive)
        jobs = [{"title": "Developer", "link": "", "description": "Writes features", "hash": "xyz"}]
        db.update_company("Corp", jobs)

        # Re-load from disk
        db2 = DatabaseManager(temp_archive)
        assert "xyz" in db2.get_archived_jobs("Corp")
        assert db2.get_archived_jobs("Corp")["xyz"]["description"] == "Writes features"

    def test_update_replaces_old_jobs(self, temp_archive):
        db = DatabaseManager(temp_archive)
        db.update_company("ACME", [{"title": "Old", "link": "", "hash": "old_hash"}])
        db.update_company("ACME", [{"title": "New", "link": "", "hash": "new_hash"}])
        archived = db.get_archived_jobs("ACME")
        assert "old_hash" not in archived
        assert "new_hash" in archived

    def test_all_companies(self, temp_archive):
        db = DatabaseManager(temp_archive)
        db.update_company("A", [{"title": "Engineer", "link": "", "hash": "h1"}])
        db.update_company("B", [{"title": "Manager", "link": "", "hash": "h2"}])
        assert set(db.all_companies()) == {"A", "B"}

    def test_invalid_json_starts_fresh(self, tmp_path):
        bad_archive = tmp_path / "bad.json"
        bad_archive.write_text("not valid json")
        db = DatabaseManager(str(bad_archive))
        assert db.get_archived_jobs("Any") == {}

    def test_find_new_jobs(self):
        current = [
            {"title": "A", "link": "", "hash": "hash_a"},
            {"title": "B", "link": "", "hash": "hash_b"},
        ]
        archived = {"hash_a": {"title": "A", "link": "", "hash": "hash_a"}}
        new_jobs = DatabaseManager.find_new_jobs(current, archived)
        assert len(new_jobs) == 1
        assert new_jobs[0]["hash"] == "hash_b"

    def test_find_new_jobs_none_when_all_seen(self):
        job = {"title": "A", "link": "", "hash": "hash_a"}
        new_jobs = DatabaseManager.find_new_jobs([job], {"hash_a": job})
        assert new_jobs == []

    def test_find_closed_jobs(self):
        archived = {
            "hash_a": {"title": "A", "link": "", "hash": "hash_a"},
            "hash_b": {"title": "B", "link": "", "hash": "hash_b"},
        }
        current = [{"title": "A", "link": "", "hash": "hash_a"}]
        closed = DatabaseManager.find_closed_jobs(current, archived)
        assert len(closed) == 1
        assert closed[0]["hash"] == "hash_b"

    def test_find_closed_jobs_none_when_all_present(self):
        job = {"title": "A", "link": "", "hash": "hash_a"}
        closed = DatabaseManager.find_closed_jobs([job], {"hash_a": job})
        assert closed == []


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class TestReporter:
    def _make_result(self, company, new_jobs, closed_jobs, error=None):
        return {
            "company": company,
            "new_jobs": new_jobs,
            "closed_jobs": closed_jobs,
            "error": error,
        }

    def test_prints_without_error(self, capsys):
        results = [
            self._make_result(
                "ACME",
                [{"title": "Software Engineer", "link": "https://acme.com/1", "hash": "h1"}],
                [],
            )
        ]
        print_report(results)
        captured = capsys.readouterr()
        assert "ACME" in captured.out
        assert "Software Engineer" in captured.out
        assert "1 new job" in captured.out

    def test_prints_error_company(self, capsys):
        results = [self._make_result("Bad Corp", [], [], error="Timeout")]
        print_report(results)
        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        assert "Timeout" in captured.out

    def test_no_new_jobs_message(self, capsys):
        results = [self._make_result("ACME", [], [])]
        print_report(results)
        captured = capsys.readouterr()
        assert "No new jobs" in captured.out

    def test_closed_jobs_shown_when_enabled(self, capsys):
        results = [
            self._make_result(
                "ACME",
                [],
                [{"title": "Old Job", "link": "", "hash": "old"}],
            )
        ]
        print_report(results, show_closed=True)
        captured = capsys.readouterr()
        assert "Old Job" in captured.out

    def test_closed_jobs_hidden_when_disabled(self, capsys):
        results = [
            self._make_result(
                "ACME",
                [],
                [{"title": "Old Job", "link": "", "hash": "old"}],
            )
        ]
        print_report(results, show_closed=False)
        captured = capsys.readouterr()
        assert "Old Job" not in captured.out

    def test_summary_counts(self, capsys):
        results = [
            self._make_result(
                "A",
                [{"title": "Eng", "link": "", "hash": "h1"},
                 {"title": "Mgr", "link": "", "hash": "h2"}],
                [],
            ),
            self._make_result("B", [], []),
        ]
        print_report(results)
        captured = capsys.readouterr()
        assert "2 new job(s)" in captured.out
        assert "2 companies" in captured.out

    def test_summary_singular_company(self, capsys):
        results = [self._make_result("A", [], [])]
        print_report(results)
        captured = capsys.readouterr()
        assert "1 company" in captured.out
