import html
import json
import re
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from tracker.config import setup_logging

logger = setup_logging()

# Fetches a posting's description text for fit scoring, through the same public
# job-board APIs used elsewhere (no logins). LinkedIn uses its guest endpoint.
MAX_CHARS = 8000
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_ashby_boards: Dict[str, Dict[str, str]] = {}  # org -> {job id: description}, per run

def _text(markup: str) -> str:
    """HTML (possibly entity-escaped) -> plain text with line breaks kept."""
    if not markup:
        return ""
    soup = BeautifulSoup(html.unescape(markup), "html.parser")
    text = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()

def _greenhouse(url: str) -> Optional[str]:
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#]+)/jobs/(\d+)", url)
    if not m:
        return None
    data = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}", timeout=8).json()
    return _text(data.get("content", ""))

def _lever(url: str) -> Optional[str]:
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]+)", url)
    if not m:
        return None
    data = requests.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}?mode=json", timeout=8).json()
    parts = [data.get("descriptionPlain", "")]
    for section in data.get("lists") or []:
        parts.append(section.get("text", ""))
        parts.append(_text(section.get("content", "")))
    parts.append(data.get("additionalPlain", ""))
    return "\n".join(p for p in parts if p)

def _ashby(url: str) -> Optional[str]:
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    org, job_id = m.groups()
    if org not in _ashby_boards:
        data = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=10).json()
        _ashby_boards[org] = {j["id"]: j.get("descriptionPlain", "") for j in data.get("jobs", [])}
    return _ashby_boards[org].get(job_id)

def _smartrecruiters(url: str) -> Optional[str]:
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return None
    data = requests.get(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}", timeout=8).json()
    sections = (data.get("jobAd") or {}).get("sections") or {}
    keys = ("jobDescription", "qualifications", "additionalInformation")
    return "\n".join(_text((sections.get(k) or {}).get("text", "")) for k in keys).strip()

def _workday(url: str) -> Optional[str]:
    m = re.match(r"https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/[^?#]+)", url)
    if not m:
        return None
    host, site, path = m.groups()
    info = requests.get(f"https://{host}/wday/cxs/{host.split('.')[0]}/{site}{path}", timeout=8).json().get("jobPostingInfo", {})
    return _text(info.get("jobDescription", ""))

def _linkedin(url: str) -> Optional[str]:
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d+)", url)
    if not m:
        return None
    for wait in (5, 10, None):  # guest endpoint; back off on rate limits like the search does
        resp = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}", headers=HEADERS, timeout=8)
        if resp.status_code != 429 or wait is None:
            break
        time.sleep(wait)
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    criteria = " | ".join(li.get_text(" ", strip=True) for li in soup.select(".description__job-criteria-item"))
    text = _text(str(body)) if body else ""
    return f"{text}\n{criteria}".strip()

def _generic(url: str) -> Optional[str]:
    """Any other careers page: the schema.org JobPosting description, else the page's text."""
    resp = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
    if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "html"):
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("description"):
                return _text(item["description"])
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    return _text(str(soup.body or soup))

def fetch_description(url: str) -> str:
    """Returns the posting's description as plain text ("" if it couldn't be read)."""
    if not url:
        return ""
    try:
        if "greenhouse.io" in url:
            text = _greenhouse(url)
        elif "jobs.lever.co" in url:
            text = _lever(url)
        elif "jobs.ashbyhq.com" in url:
            text = _ashby(url)
        elif "smartrecruiters.com" in url:
            text = _smartrecruiters(url)
        elif "myworkdayjobs.com" in url:
            text = _workday(url)
        elif "linkedin.com/jobs" in url:
            text = _linkedin(url)
        else:
            text = None
        if not text:
            text = _generic(url) if "linkedin.com" not in url else ""
    except Exception as e:
        logger.debug(f"Description fetch failed for {url}: {e}")
        return ""
    return (text or "")[:MAX_CHARS]
