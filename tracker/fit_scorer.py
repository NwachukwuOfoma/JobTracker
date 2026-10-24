import hashlib
import re
import subprocess
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tracker.config import RESUME_NAME, setup_logging
from tracker.database import get_job_descriptions, save_job_descriptions
from tracker.job_details import fetch_description
from tracker.salary_estimator import _load_api_key

logger = setup_logging()

# Scores how well each unvisited job matches your resume (0-100) so the dashboard
# can sort by fit. Nothing is hidden: a low score only moves a job down the list.
MODEL = "claude-haiku-5-5"
MAX_WORKERS = 4
FETCH_WORKERS = 12
LINKEDIN_FETCH_WORKERS = 2  # LinkedIn's guest endpoint rate-limits quickly
# Facts about you that aren't on the resume (e.g. "US citizen"), one per line.
# Kept outside the repository because it's personal.
NOTES_FILE = Path.home() / ".config" / "jobtracker" / "candidate_notes.txt"
SEARCH_DIRS = [Path.home() / d for d in ("Downloads", "Documents", "Desktop")]

# Strict requirements that hide a job entirely (it's marked skipped and never shown)
DEALBREAKERS = {
    "phd_required": "PhD required",
    "active_clearance_required": "Active clearance required",
    "non_us_location": "Outside the US",
    "publications_required": "Publications required",
}
# Bump when the scoring instructions change in a way that should re-score every job
SCORING_VERSION = "2"

REPORT_TOOL = {
    "name": "report_fit",
    "description": "Report how well the candidate fits this job.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "description": "0-100 fit score."},
            "note": {"type": "string", "description": "One short sentence (under 20 words): the strongest match and the biggest gap."},
            "dealbreakers": {
                "type": "array",
                "items": {"type": "string", "enum": list(DEALBREAKERS)},
                "description": "Strict requirements that rule the candidate out; see the system prompt. Empty if none.",
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "At most 3 hard requirements (stated as required, not preferred) the resume doesn't meet, 2-4 words each, e.g. 'Security clearance', 'US citizenship', '5+ years', 'PhD required'. Never skills, locations, nice-to-haves, or anything the candidate's other facts say they meet (such as citizenship). Empty if none.",
            },
        },
        "required": ["score", "note", "dealbreakers", "flags"],
        "additionalProperties": False,
    },
}

def find_latest_resume() -> Optional[Path]:
    """The most recently modified PDF/Word file named like the resume (cover letters excluded)."""
    found = set()
    try:
        out = subprocess.run(["mdfind", "-name", RESUME_NAME], capture_output=True, text=True, timeout=10).stdout
        found.update(Path(line) for line in out.splitlines() if line)
    except (OSError, subprocess.SubprocessError):
        pass
    for folder in SEARCH_DIRS:
        found.update(folder.glob(f"{RESUME_NAME}*"))
    candidates = [
        p for p in found
        if p.is_file()
        and p.name.startswith(RESUME_NAME)
        and p.suffix.lower() in (".pdf", ".docx")
        and "cover" not in p.name.lower()
        and ".Trash" not in p.parts and "Library" not in p.parts
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)

def read_resume(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf8")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    return "\n".join(re.sub(r"<[^>]+>", "", p) for p in paragraphs).strip()

def load_resume() -> Tuple[Optional[str], Optional[str], Optional[Path]]:
    """Returns (resume text, short hash of it, path), or Nones if no resume was found."""
    path = find_latest_resume()
    if not path:
        return None, None, None
    try:
        text = read_resume(path)
    except Exception as e:
        logger.warning(f"Couldn't read resume {path.name}: {e}")
        return None, None, None
    if not text:
        return None, None, None
    try:
        notes = NOTES_FILE.read_text().strip()
    except OSError:
        notes = ""
    if notes:
        text += f"\n\nOther facts about the candidate (not on the resume):\n{notes}"
    # The hash covers the notes too, so editing them re-scores jobs like a new resume does
    return text, hashlib.sha256((SCORING_VERSION + text).encode()).hexdigest()[:12], path

def _system_prompt(resume: str) -> str:
    return f"""Today's date is {date.today().isoformat()}. You screen job postings for a new-grad candidate in the US, scoring how well each one fits their resume.

<resume>
{resume}
</resume>

Score 0-100:
- 80-100: strong match in skills and domain, and the level is right for a new grad.
- 60-79: good match with some gaps worth applying through.
- 40-59: partial match; noticeably different focus or stack.
- 0-39: poor match (different field, clearly senior, or hard requirements they lack).

Weigh the role's actual work and required skills most. Treat "1-3 years" asks as soft: new grads with internships often get these roles, so dock only a few points. Required 4+ years, a required PhD, or a title clearly above entry level caps the score at 50. If the description is missing, score from the title and company and say so in the note.

Dealbreakers (only when the posting states them as hard requirements; "preferred", "a plus", "ability to obtain" or "eligible for" never count):
- phd_required: a PhD (or MD) is required, not just preferred.
- active_clearance_required: the candidate must already hold an active security clearance at hire. Roles where a clearance can be obtained after hire don't count.
- non_us_location: the job is based outside the United States, or remote only from outside the US.
- publications_required: a publication record (e.g. first-author papers at top venues) is required.

Call report_fit once."""

def _score_one(client, system: str, job: Dict, description: str) -> Optional[Dict]:
    import anthropic

    location = (job.get("location") or "").split(" / ")[0]
    content = (
        f"Company: {job['company']}\nTitle: {job['title']}\nLocation: {location or 'unknown'}\n\n"
        f"Description:\n{description or '(not available)'}"
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=[REPORT_TOOL],
            tool_choice={"type": "tool", "name": "report_fit"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as e:
        logger.warning(f"Fit score failed for {job['company']} - {job['title']}: {e}")
        return None
    for block in response.content:
        if block.type == "tool_use":
            fit = dict(block.input)
            fit["score"] = max(0, min(100, int(fit["score"])))
            fit["dealbreaker_labels"] = [f"Hidden: {DEALBREAKERS[d]}" for d in fit.get("dealbreakers", []) if d in DEALBREAKERS]
            return fit
    return None

def _descriptions(jobs: List[Dict]) -> Dict[str, str]:
    """Saved descriptions, plus freshly fetched ones for jobs that don't have one yet."""
    have = get_job_descriptions([j["normalized_url"] for j in jobs])
    missing = [j for j in jobs if j["normalized_url"] not in have]
    linkedin_slots = threading.Semaphore(LINKEDIN_FETCH_WORKERS)

    def fetch(job):
        # The employer's own page first; for LinkedIn jobs fall back to the LinkedIn post
        urls = [u for u in (job.get("apply_url"), job.get("original_url")) if u]
        text = ""
        for url in dict.fromkeys(urls):
            if "linkedin.com" in url:
                with linkedin_slots:
                    text = fetch_description(url)
            else:
                text = fetch_description(url)
            if len(text) >= 300:
                break
        return job["normalized_url"], text

    fetched = {}
    if missing:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
            fetched = {url: text for url, text in executor.map(fetch, missing) if text}
        save_job_descriptions(fetched)
    return {**have, **fetched}

def score_jobs(jobs: List[Dict]) -> Tuple[Dict[str, Dict], Optional[str]]:
    """
    Scores the given jobs against the newest resume. Returns ({normalized_url: {"score",
    "note", "flags"}}, resume hash). Failed calls are left out and retried next fetch.
    Returns ({}, None) when there's no resume or API key.
    """
    resume, resume_hash, path = load_resume()
    key = _load_api_key()
    if not jobs or not resume or not key:
        return {}, resume_hash
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=5)
    jobs = [j for j in jobs if j.get("fit_resume_hash") != resume_hash]
    if not jobs:
        return {}, resume_hash
    logger.info(f"Scoring fit for {len(jobs)} job(s) against {path.name}...")
    descriptions = _descriptions(jobs)
    system = _system_prompt(resume)

    def run(job):
        return job["normalized_url"], _score_one(client, system, job, descriptions.get(job["normalized_url"], ""))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        fits = {url: fit for url, fit in executor.map(run, jobs) if fit}
    logger.info(f"Fit scores: {len(fits)} scored, {len(jobs) - len(fits)} failed.")
    return fits, resume_hash
