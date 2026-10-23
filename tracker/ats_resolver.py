import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Any

import requests

from tracker.config import BASE_DIR, setup_logging

logger = setup_logging()

# Which ATS board (if any) each company uses is cached so the guessing below
# only happens once a week per company, not on every fetch.
BOARD_CACHE_PATH = BASE_DIR / "cache" / "ats_boards.json"
BOARD_CACHE_TTL = 7 * 24 * 3600

ATS_APIS = {
    "greenhouse": (
        "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        lambda d: [(j["title"], j["absolute_url"]) for j in d.get("jobs", [])],
    ),
    "lever": (
        "https://api.lever.co/v0/postings/{token}?mode=json",
        lambda d: [(j["text"], j["hostedUrl"]) for j in d] if isinstance(d, list) else [],
    ),
    "ashby": (
        "https://api.ashbyhq.com/posting-api/job-board/{token}",
        lambda d: [(j["title"], j["jobUrl"]) for j in d.get("jobs", [])],
    ),
}

def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())

def _norm_company(company: str) -> str:
    return company.lower().strip()

def _candidate_tokens(company: str) -> List[str]:
    """Guesses board tokens from a company name, e.g. 'Scout AI, Inc.' -> scoutai, scout-ai.
    (The first word alone isn't tried: 'Relativity Space' would hit Relativity's board.)"""
    cleaned = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|labs)\b\.?", "", company.lower())
    words = re.sub(r"[^a-z0-9 ]", "", cleaned).split()
    if not words:
        return []
    return list(dict.fromkeys(["".join(words), "-".join(words)]))

def _fetch_board(ats: str, token: str) -> Optional[List[Tuple[str, str]]]:
    """Returns the (title, url) postings on a board, or None if the board doesn't exist."""
    url_template, extract = ATS_APIS[ats]
    try:
        resp = requests.get(url_template.format(token=token), timeout=5)
        if resp.status_code != 200:
            return None
        return extract(resp.json()) or None
    except Exception:
        return None

def _find_board(company: str) -> Optional[Dict[str, str]]:
    for token in _candidate_tokens(company):
        for ats in ATS_APIS:
            if _fetch_board(ats, token):
                return {"ats": ats, "token": token}
    return None

def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(BOARD_CACHE_PATH.read_text())
    except Exception:
        return {}

def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        BOARD_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BOARD_CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))
    except Exception as e:
        logger.warning(f"Could not save ATS board cache: {e}")

def resolve_apply_urls(linkedin_jobs: List[Dict], other_jobs: List[Dict]) -> Dict[str, str]:
    """
    Finds the employer's own application link for LinkedIn jobs, without touching
    LinkedIn. A job is matched (by company + exact title) against:
      1. the same job already scraped from a GitHub board, then
      2. the company's public Greenhouse / Lever / Ashby job board.
    Returns {normalized_url: apply_url} for the jobs that matched.
    """
    resolved: Dict[str, str] = {}

    github_index = {
        (_norm_company(j["company"]), _norm_title(j["title"])): j.get("original_url") or j.get("url")
        for j in other_jobs
    }
    remaining = []
    for job in linkedin_jobs:
        hit = github_index.get((_norm_company(job["company"]), _norm_title(job["title"])))
        if hit:
            resolved[job["normalized_url"]] = hit
        else:
            remaining.append(job)
    if not remaining:
        return resolved

    cache = _load_cache()
    now = time.time()
    companies = sorted({j["company"] for j in remaining})
    stale = [c for c in companies if now - cache.get(_norm_company(c), {}).get("checked", 0) > BOARD_CACHE_TTL]

    with ThreadPoolExecutor(max_workers=16) as executor:
        for company, board in zip(stale, executor.map(_find_board, stale)):
            cache[_norm_company(company)] = {"board": board, "checked": now}
    _save_cache(cache)

    boards = {c: cache[_norm_company(c)]["board"] for c in companies if cache[_norm_company(c)]["board"]}
    with ThreadPoolExecutor(max_workers=16) as executor:
        postings = dict(zip(boards, executor.map(lambda c: _fetch_board(boards[c]["ats"], boards[c]["token"]) or [], boards)))

    for job in remaining:
        for title, url in postings.get(job["company"], []):
            if _norm_title(title) == _norm_title(job["title"]):
                resolved[job["normalized_url"]] = url
                break

    return resolved
