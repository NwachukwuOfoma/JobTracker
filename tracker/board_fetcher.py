import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any, Optional

import requests
from bs4 import BeautifulSoup

from tracker.ats_resolver import BOARD_CACHE_PATH
from tracker.config import setup_logging
from tracker.normalizer import normalize_url
from tracker.scraper import is_us_or_remote

logger = setup_logging()

REPOSITORY = "company-boards"
MAX_AGE_DAYS = 30  # same window as the LinkedIn search
WATCHLIST_LOOKBACK_DAYS = 90  # companies seen in your feeds within this window are watched

# Roles worth surfacing; senior/staff/PhD titles are dropped later by the pipeline's filters
RELEVANT_TITLE_RE = re.compile(
    r"\b(ai|ml|machine learning|artificial intelligence|deep learning|computer vision|nlp|"
    r"natural language|llm|generative|genai|data scien\w*|applied scien\w*|"
    r"research (engineer|scientist)|perception|reinforcement learning)\b",
    re.IGNORECASE,
)
INTERN_RE = re.compile(r"\bintern(ship)?\b", re.IGNORECASE)
# AI-flavoured titles that aren't engineering/research roles
NON_TECHNICAL_RE = re.compile(
    r"\b(sales|account (executive|manager)|marketing|recruit\w*|counsel|legal|policy|"
    r"business development|partnerships?|customer success|go.to.market|gtm|communications|"
    r"content|writer|designer|administrative|executive assistant)\b",
    re.IGNORECASE,
)
# Company boards list worldwide roles; "Remote - India" would otherwise pass as remote
NON_US_RE = re.compile(
    r"\b(india|canada|toronto|vancouver|uk|united kingdom|london|ireland|dublin|germany|berlin|"
    r"munich|france|paris|spain|netherlands|amsterdam|poland|switzerland|zurich|europe|emea|apac|"
    r"latam|brazil|mexico|argentina|singapore|japan|tokyo|korea|seoul|china|australia|sydney|"
    r"israel|tel aviv|philippines|vietnam|bangalore|bengaluru|hyderabad|pune|chennai|noida|gurgaon|"
    r"gurugram|mumbai|delhi|krakow|warsaw|prague|bucharest|cluj|budapest|sofia|manila|taipei|taiwan|"
    r"shanghai|beijing|shenzhen|hong kong|malaysia|kuala lumpur|costa rica|colombia|bogota|chile|"
    r"belgium|leuven|brussels|italy|milan|sweden|stockholm|denmark|copenhagen|finland|norway|oslo|"
    r"austria|vienna, austria|portugal|lisbon|greece|turkey|istanbul|egypt|cairo|nigeria|lagos|kenya|"
    r"south africa|uae|dubai|abu dhabi|saudi|riyadh|qatar|indonesia|jakarta|thailand|bangkok|"
    r"new zealand|auckland|scotland|edinburgh|wales|cambridge, uk|ukraine|romania|serbia|croatia|"
    r"lithuania|latvia|estonia|czech|slovakia|hungary|bulgaria|peru|uruguay|ontario|quebec|montreal|"
    r"british columbia|alberta|calgary|ottawa|el salvador|san salvador|guatemala|honduras|"
    r"dominican republic|puerto rico, mx)\b",
    re.IGNORECASE,
)
US_EXPLICIT_RE = re.compile(r"\b(us|usa|u\.s\.|united states|americas|north america)\b", re.IGNORECASE)
US_STATE_RE = re.compile(r",\s*[A-Z]{2}\b")  # "New York, NY"

def _is_us_location(location: str) -> bool:
    if NON_US_RE.search(location or "") and not (US_EXPLICIT_RE.search(location) or US_STATE_RE.search(location)):
        return False
    return is_us_or_remote(location)

# Job aggregators that repost other companies' listings
AGGREGATOR_BOARDS = {"jobgether"}

BOARD_URL_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([a-z0-9_-]+)", re.IGNORECASE)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_.-]+)", re.IGNORECASE)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)/")),
    # token is "host|site", e.g. "nvidia.wd5.myworkdayjobs.com|NVIDIAExternalCareerSite"
    ("workday", re.compile(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)/", re.IGNORECASE)),
]
# Workday and SmartRecruiters boards are searched instead of downloaded whole
SEARCH_TERMS = ["machine learning", "AI", "data scientist"]
# Workday boards are the slowest and most numerous; its broad "AI" search mostly
# returns older or non-technical roles, so only the two precise terms are used there
WORKDAY_SEARCH_TERMS = ["machine learning", "data scientist"]
# "Engineer 4", "Scientist III": numbered levels above 2 are senior roles
SENIOR_LEVEL_RE = re.compile(
    r"\b(engineer|scientist|developer|analyst)\s+(iii|iv|v|[3-9])\b|\blevel\s*[3-9]\b|\bvice president\b",
    re.IGNORECASE,
)

def _parse_date(value: Any) -> datetime:
    if isinstance(value, (int, float)):  # Lever: epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)

def _greenhouse(token: str) -> List[Dict]:
    data = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=8).json()
    return [{
        "title": j["title"], "url": j["absolute_url"],
        "location": (j.get("location") or {}).get("name", ""),
        "posted": _parse_date(j.get("first_published") or j.get("updated_at")),
        "salary": "",
    } for j in data.get("jobs", [])]

def _lever(token: str) -> List[Dict]:
    # Lever's JSON API returns every posting with its full description (tens of MB
    # for big boards) and can't be sorted or trimmed, so read the public board page,
    # which lists just titles, locations and links. It has no posting dates; new
    # postings are still detected because jobs are tracked by URL.
    resp = requests.get(f"https://jobs.lever.co/{token}", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    postings = []
    for post in soup.select("div.posting"):
        title, link = post.select_one("[data-qa=posting-name]"), post.select_one("a.posting-title")
        if not title or not link:
            continue
        loc = post.select_one(".sort-by-location") or post.select_one(".workplaceTypes")
        postings.append({
            "title": title.get_text(strip=True), "url": link["href"],
            "location": loc.get_text(strip=True) if loc else "",
            "posted": None, "salary": "",
        })
    return postings

def _ashby(token: str) -> List[Dict]:
    data = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true", timeout=8
    ).json()
    return [{
        "title": j["title"], "url": j["jobUrl"],
        "location": "Remote" if j.get("isRemote") else j.get("location", ""),
        "posted": _parse_date(j.get("publishedAt")),
        "salary": ((j.get("compensation") or {}).get("compensationTierSummary") or ""),
    } for j in data.get("jobs", []) if j.get("isListed", True)]

def _workday_posted(text: str) -> Optional[datetime]:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago'; None for 'Posted 30+ Days Ago'."""
    text = (text or "").lower()
    if "30+" in text:
        return None
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        m = re.search(r"(\d+)", text)
        days = int(m.group(1)) if m else 0
    return datetime.now(timezone.utc) - timedelta(days=days)

def _workday(token: str) -> List[Dict]:
    # The same search endpoint Workday's public career pages call. Results are
    # sorted by relevance, so each search term's first page is checked.
    host, site = token.split("|", 1)
    tenant = host.split(".")[0]
    postings, seen = [], set()
    for term in WORKDAY_SEARCH_TERMS:
        resp = requests.post(
            f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
            json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term},
            timeout=8,
        )
        if resp.status_code == 429:
            time.sleep(3)
            continue
        if resp.status_code != 200:
            return postings  # board moved or doesn't exist; skip the other terms
        for j in resp.json().get("jobPostings", []):
            path = j.get("externalPath", "")
            posted = _workday_posted(j.get("postedOn", ""))
            if not path or path in seen or posted is None:
                continue
            seen.add(path)
            locations = j.get("locationsText", "")
            postings.append({
                "title": j.get("title", ""), "url": f"https://{host}/en-US/{site}{path}",
                # "2 Locations" says nothing, so fall back to the location in the job's path
                "location": locations if not re.match(r"\d+ locations", locations, re.I) else path.split("/")[2] if path.count("/") >= 3 else "",
                "posted": posted, "salary": "", "location_unverified": True,
            })
    return postings

def _smartrecruiters(token: str) -> List[Dict]:
    postings, seen = [], set()
    for term in SEARCH_TERMS:
        resp = requests.get(
            f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
            params={"q": term, "limit": 100}, timeout=8,
        )
        if resp.status_code != 200:
            return postings
        for j in resp.json().get("content", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            loc = j.get("location") or {}
            country = (loc.get("country") or "").upper()
            postings.append({
                "title": j.get("name", ""), "url": f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                "location": ("Remote, " if loc.get("remote") else "") + ", ".join(
                    x for x in (loc.get("city"), loc.get("region"), "USA" if country == "US" else country) if x),
                "posted": _parse_date(j.get("releasedDate")), "salary": "",
            })
    return postings

FETCHERS = {
    "greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby,
    "workday": _workday, "smartrecruiters": _smartrecruiters,
    # Workable isn't included: its API rate-limits automated use for ~24h and asks
    # for a partner XML feed instead.
}

def build_watchlist(tracked_jobs: Dict[str, Dict]) -> Dict[Tuple[str, str], str]:
    """
    The companies to watch are picked automatically: every company with a public
    Greenhouse / Lever / Ashby board that appeared in your GitHub or LinkedIn
    results recently. Returns {(ats, board_token): company display name}.
    """
    cutoff = (datetime.now() - timedelta(days=WATCHLIST_LOOKBACK_DAYS)).isoformat()
    names_by_company = {}
    watchlist: Dict[Tuple[str, str], str] = {}
    for job in tracked_jobs.values():
        if (job.get("date_first_seen") or "") < cutoff:
            continue
        names_by_company.setdefault(job["company"].lower().strip(), job["company"])
        url = job.get("original_url") or ""
        for ats, pattern in BOARD_URL_PATTERNS:
            m = pattern.search(url)
            if m:
                if ats == "workday":
                    token = f"{m.group(1).lower()}|{m.group(2)}"
                elif ats == "smartrecruiters":
                    token = m.group(1)  # company identifiers are case-sensitive
                else:
                    token = m.group(1).lower()
                watchlist.setdefault((ats, token), job["company"])

    # Boards discovered while looking up direct apply links for LinkedIn jobs
    try:
        cache = json.loads(BOARD_CACHE_PATH.read_text())
    except Exception:
        cache = {}
    for company, entry in cache.items():
        board = entry.get("board")
        if board and company in names_by_company:
            watchlist.setdefault((board["ats"], board["token"]), names_by_company[company])
    return watchlist

def fetch_board_jobs(tracked_jobs: Dict[str, Dict], max_workers: int = 48) -> List[Dict]:
    """Fetches recent, US/remote, AI/ML-relevant postings from every watched company board."""
    watchlist = {b: c for b, c in build_watchlist(tracked_jobs).items() if b[1] not in AGGREGATOR_BOARDS}
    logger.info(f"Checking {len(watchlist)} company job boards...")
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    def fetch(board):
        ats, token = board
        try:
            return FETCHERS[ats](token)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(fetch, watchlist))

    jobs = []
    for (board, company), postings in zip(watchlist.items(), results):
        for p in postings:
            title = p["title"]
            if not RELEVANT_TITLE_RE.search(title) or INTERN_RE.search(title) or NON_TECHNICAL_RE.search(title) or SENIOR_LEVEL_RE.search(title):
                continue
            if p["posted"] and p["posted"] < cutoff:
                continue
            us_ok = (not NON_US_RE.search(p["location"])) if p.get("location_unverified") else _is_us_location(p["location"])
            if not us_ok:
                continue
            age = f"{(datetime.now(timezone.utc) - p['posted']).days}d" if p["posted"] else ""
            jobs.append({
                "normalized_url": normalize_url(p["url"]),
                "url": p["url"],
                "company": company,
                "title": p["title"].strip(),
                "location": p["location"] or "Unknown",
                "repository": REPOSITORY,
                "source": REPOSITORY,
                "category": "All Roles",
                "salary": p["salary"],
                "age": age,
                "status": "new",
            })
    logger.info(f"Found {len(jobs)} relevant postings on company boards.")
    return jobs
