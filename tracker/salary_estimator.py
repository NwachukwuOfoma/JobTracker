import os
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from tracker.config import setup_logging
from tracker.normalizer import HOURS_PER_YEAR, job_identity_key, parse_annual_salary

logger = setup_logging()

# Fills in salaries the scrapers couldn't find by having Claude search the web,
# the same "<company> <title> <location> salary" lookup you'd do by hand.
MODEL = "claude-haiku-5-5"
MAX_SEARCHES_PER_JOB = 3
# Each lookup reads ~50k tokens of search results; new API accounts are limited to
# ~500k input tokens/minute, so more parallel lookups just wait on rate-limit retries
MAX_WORKERS = 4

# The background server (launchd) doesn't inherit your shell's environment, so the
# key can also live in this private file, outside the repository.
API_KEY_FILE = Path.home() / ".config" / "jobtracker" / "anthropic_api_key"

SYSTEM_PROMPT = f"""Today's date is {date.today().isoformat()}. You find the base pay for one job posting in the United States.

Search for this specific posting first (the company's careers page, LinkedIn, the job board it was posted on). Many US postings list a pay range; if you find this posting's range, report it as posted. If no posted range exists, give a realistic base-salary estimate for this exact role, level, company and location, using sources such as Levels.fyi, Glassdoor, H-1B salary data or the company's postings for similar roles. Your training data ends well before today's date, so rely on what you find rather than memory.

When you have an answer, call report_salary exactly once. Report base salary only (no equity or bonus). If you truly cannot find or estimate anything, call report_salary with low and high set to 0."""

REPORT_TOOL = {
    "name": "report_salary",
    "description": "Report the job's base pay range once you've found it or estimated it.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "low": {"type": "number", "description": "Bottom of the range in USD (0 if unknown)."},
            "high": {"type": "number", "description": "Top of the range in USD (0 if unknown)."},
            "pay_period": {"type": "string", "enum": ["year", "hour"]},
            "posted": {"type": "boolean", "description": "True if this posting itself lists the range; false for an estimate."},
            "basis": {"type": "string", "description": "A few words on where the figure comes from."},
        },
        "required": ["low", "high", "pay_period", "posted", "basis"],
        "additionalProperties": False,
    },
}

def _load_api_key() -> Optional[str]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return API_KEY_FILE.read_text().strip() or None
    except OSError:
        return None

def _client():
    key = _load_api_key()
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("Salary estimates skipped: the 'anthropic' package isn't installed (pip install anthropic).")
        return None
    return anthropic.Anthropic(api_key=key)

def _format(report: Dict) -> str:
    """Turns a report into the salary string stored in the DB ("" when nothing was found)."""
    low, high = report.get("low") or 0, report.get("high") or 0
    if high <= 0 and low <= 0:
        return ""
    low, high = low or high, high or low
    hourly_note = ""
    if report.get("pay_period") == "hour":
        hourly_note = f"from ${low:,.2f} - ${high:,.2f}/hr"
        low, high = low * HOURS_PER_YEAR, high * HOURS_PER_YEAR
    text = f"${low:,.0f}" if low == high else f"${low:,.0f} - ${high:,.0f}"
    notes = ([] if report.get("posted") else ["Est."]) + ([hourly_note] if hourly_note else [])
    return f"{text} ({', '.join(notes)})" if notes else text

def _estimate_one(client, job: Dict) -> Optional[str]:
    """Returns a salary string, "" if Claude found nothing, or None if the call failed (retry next fetch)."""
    import anthropic

    location = (job.get("location") or "").split(" / ")[0]
    messages = [{
        "role": "user",
        "content": (
            f"Company: {job['company']}\nTitle: {job['title']}\nLocation: {location or 'United States'}\n"
            f"Posting URL: {job.get('apply_url') or job.get('original_url') or job.get('url') or 'unknown'}"
        ),
    }]
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES_PER_JOB},
        REPORT_TOOL,
    ]
    try:
        for _ in range(4):  # a long search turn can come back as pause_turn; resume it
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                tool_choice={"type": "auto"},
                output_config={"effort": "medium"},
                messages=messages,
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "report_salary":
                    return _format(block.input)
            if response.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": response.content}]
                continue
            return ""  # finished without reporting
        return ""
    except anthropic.AuthenticationError:
        raise
    except anthropic.APIError as e:
        logger.warning(f"Salary estimate failed for {job['company']} - {job['title']}: {e}")
        return None

def estimate_salaries(jobs: List[Dict]) -> Dict[str, str]:
    """
    Looks up salaries for jobs that have none. Returns {normalized_url: salary string};
    "" means Claude looked and found nothing, so the job isn't looked up again.
    Jobs whose call failed are left out and retried on the next fetch.
    Returns {} without doing anything when no API key is configured.
    """
    if not jobs:
        return {}
    client = _client()
    if client is None:
        return {}

    import anthropic

    results: Dict[str, str] = {}

    def run(job):
        try:
            return job["normalized_url"], _estimate_one(client, job)
        except anthropic.AuthenticationError:
            return job["normalized_url"], None

    logger.info(f"Estimating salaries for {len(jobs)} job(s) with {MODEL} + web search...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for url, salary in executor.map(run, jobs):
            if salary is not None:
                results[url] = salary
    found = sum(1 for s in results.values() if s)
    logger.info(f"Salary estimates: {found} found, {len(results) - found} with no data, {len(jobs) - len(results)} failed.")
    return results


# Reusing salaries we already have, before paying for a search
REUSE_MAX_AGE_DAYS = 180
SIMILAR_TITLE_RATIO = 0.8
_LEVEL_RE = re.compile(
    r"\b(i{1,3}|iv|[1-5]|junior|jr|associate|entry|new grad|graduate|early career|mid|senior|sr|staff|principal|lead)\b"
)

def _title_level(title: str) -> set:
    return set(_LEVEL_RE.findall(title.lower()))

def _salary_core(salary: str) -> str:
    """'$140,000 - $170,000 (Est.)' -> '$140,000 - $170,000'."""
    return salary.split(" (")[0].strip()

def reuse_known_salaries(jobs: List[Dict], tracked_jobs: Dict[str, Dict]) -> Dict[str, str]:
    """
    Free alternative to a paid lookup: copies a salary from a job we already know
    at the same company with the same title, or failing that a very similar title
    at the same level ("Machine Learning Engineer" ~ "Machine Learning Engineer,
    Growth"; "Data Scientist I" never borrows from "Data Scientist III").
    Only salaries first seen in the last 6 months are used.
    Returns {normalized_url: salary string} for the jobs that matched.
    """
    cutoff = (datetime.now() - timedelta(days=REUSE_MAX_AGE_DAYS)).isoformat()
    by_company: Dict[str, List[Dict]] = {}
    for job in tracked_jobs.values():
        salary = (job.get("salary") or "").strip()
        if salary and parse_annual_salary(salary) and (job.get("date_first_seen") or "") >= cutoff:
            by_company.setdefault(job_identity_key(job["company"], "")[0], []).append(job)

    reused: Dict[str, str] = {}
    for job in jobs:
        company_key, title_key = job_identity_key(job["company"], job["title"])
        known = [k for k in by_company.get(company_key, []) if k["normalized_url"] != job["normalized_url"]]
        if not known:
            continue
        same = next((k for k in known if job_identity_key(k["company"], k["title"])[1] == title_key), None)
        if same:
            core = _salary_core(same["salary"])
            reused[job["normalized_url"]] = f"{core} (Est., same role)"
            continue
        level = _title_level(job["title"])
        scored = [
            (SequenceMatcher(None, job["title"].lower(), k["title"].lower()).ratio(), k)
            for k in known if _title_level(k["title"]) == level
        ]
        ratio, best = max(scored, key=lambda x: x[0], default=(0, None))
        if best and ratio >= SIMILAR_TITLE_RATIO:
            reused[job["normalized_url"]] = f"{_salary_core(best['salary'])} (Est., similar role)"
    return reused
