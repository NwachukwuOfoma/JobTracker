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
WORKDAY_COUNTRY_CACHE = BOARD_CACHE_PATH.parent / "posting_countries.json"
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
    r"dominican republic|puerto rico, mx|melbourne|brisbane|adelaide|anz|singapore|glasgow|manchester|"
    r"bristol, uk|belfast|spain|madrid|barcelona|valencia, spain|rehovot|haifa|herzliya|jerusalem|"
    r"petah tikva|yokneam|ra'anana|netanya|beer sheva|luxembourg|monaco|iceland|reykjavik|cyprus|malta|"
    r"pakistan|karachi|lahore|bangladesh|dhaka|sri lanka|nepal|morocco|tunisia|ghana|accra|ethiopia|"
    r"rwanda|uganda|tanzania|armenia|yerevan|georgia, tbilisi|tbilisi|kazakhstan|almaty|uzbekistan|"
    r"belarus|minsk|moldova|kyiv|kiev|lviv|gdansk|wroclaw|poznan|brno|ljubljana|slovenia|zagreb|"
    r"belgrade|athens|thessaloniki|porto, portugal|seville|bilbao|lyon|marseille|toulouse|nantes|"
    r"grenoble|nice, france|hamburg|frankfurt|cologne|stuttgart|dusseldorf|dresden|leipzig|"
    r"rotterdam|eindhoven|utrecht|the hague|antwerp|ghent|geneva|lausanne|basel|gothenburg|malmo|"
    r"aarhus|espoo|tampere|bergen|cork|galway|limerick|leeds|birmingham, uk|cambridge, uk|oxford, uk|"
    r"reading, uk|nanjing|hangzhou|chengdu|wuhan|suzhou|guangzhou|osaka|kyoto|busan|hsinchu|"
    r"penang|cebu|ho chi minh|hanoi|da nang|auckland|wellington, nz|perth, wa, australia|"
    r"monterrey|guadalajara|mexico city|sao paulo|são paulo|rio de janeiro|buenos aires|santiago, chile|"
    r"lima, peru|medellin|medellín|quito|montevideo|vancouver, bc|toronto, on|waterloo, on|"
    r"kitchener|edmonton|winnipeg|halifax)\b",
    re.IGNORECASE,
)
US_EXPLICIT_RE = re.compile(r"\b(us|usa|u\.s\.|united states|americas|north america)\b", re.IGNORECASE)
US_STATE_RE = re.compile(r",\s*[A-Z]{2}\b")  # "New York, NY"
US_STATE_CODES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)

def _us_state_codes(text: str) -> set:
    """US state codes after a comma ("Austin, TX"). "ON"/"BC" (Canada) don't count, and
    neither does "IN", which next to a foreign city ("bangalore, IN") means India."""
    return {m.group(0).strip(", ").upper() for m in US_STATE_RE.finditer(text)} & US_STATE_CODES - {"IN"}

# ISO-3166 alpha-3 codes Workday-style locations use ("Rehovot,ISR"); matched case-sensitively
NON_US_COUNTRY_CODE_RE = re.compile(
    r"\b(ISR|ESP|DEU|GBR|FRA|IND|CAN|CHN|JPN|KOR|SGP|AUS|BRA|MEX|POL|NLD|IRL|CHE|SWE|ITA|PRT|BEL|AUT|"
    r"DNK|FIN|NOR|CZE|ROU|HUN|TUR|ARE|SAU|PHL|VNM|MYS|IDN|THA|TWN|HKG|ARG|COL|CHL|CRI|ZAF|EGY|NGA|"
    r"KEN|UKR|SRB|HRV|BGR|GRC|LTU|LVA|EST|SVK|SVN|LUX|NZL|PER|URY|PAK|BGD)\b"
)

def mentions_non_us_place(title: str, location: str) -> bool:
    """
    True when a job's title or location names a place outside the US and nothing in
    them points to the US, e.g. "Applied AI Architect (Brazil)" with location "Remote".
    "Remote - US / Canada" or "London, UK; New York, NY" are kept.
    """
    text = f"{title or ''} | {location or ''}"
    if not (NON_US_RE.search(text) or NON_US_COUNTRY_CODE_RE.search(text)):
        return False
    return not (US_EXPLICIT_RE.search(text) or _us_state_codes(text))

def _is_us_location(location: str) -> bool:
    if NON_US_RE.search(location or ""):
        if not (US_EXPLICIT_RE.search(location) or _us_state_codes(location)):
            return False
    return bool(_us_state_codes(location)) or is_us_or_remote(location)

# Workday locations are often bare city names, so also catch non-US roles by their titles:
# German/French/Dutch/Spanish job terms and UK/EU programme names
NON_US_TITLE_RE = re.compile(
    r"werkstudent|praktikum|praktikant|abschlussarbeit|^\W*stage\b|\bstage\s*(?:de\b|d'|en\b|[-–:])|stagiaire|alternance|alternant|"
    r"\(h/f\)|\(f/h\)|\(m/w/d\)|\(w/m/d\)|\(m/f/d\)|\(f/m/d\)|\bm/w/d\b|\bm/f/d\b|"
    r"placement year|industrial placement|graduate scheme|\bbecario\b|\bpracticas\b|\btirocinio\b|"
    r"\bingenieur\b|\bentwickler\b|\bstudent worker\b",
    re.IGNORECASE,
)

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
        location = loc.get_text(strip=True) if loc else ""
        postings.append({
            "title": title.get_text(strip=True), "url": link["href"],
            "location": location, "posted": None, "salary": "",
            "location_unverified": not location,
        })
    return postings

def _ashby(token: str) -> List[Dict]:
    data = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true", timeout=8
    ).json()
    postings = []
    for j in data.get("jobs", []):
        if not j.get("isListed", True):
            continue
        countries = {
            ((loc.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
            for loc in [j] + list(j.get("secondaryLocations") or [])
        } - {""}
        if countries and not any(_is_us_country(c) for c in countries):
            continue  # Ashby gives each location's country; skip roles with no US location
        postings.append({
            "title": j["title"], "url": j["jobUrl"],
            "location": "Remote" if j.get("isRemote") else j.get("location", ""),
            "posted": _parse_date(j.get("publishedAt")),
            "salary": ((j.get("compensation") or {}).get("compensationTierSummary") or ""),
        })
    return postings

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

def _is_us_country(country: str) -> bool:
    return (country or "").strip().lower() in {"united states", "united states of america", "us", "usa", "u.s.", "u.s.a."}

def _workday_country(url: str) -> Optional[str]:
    """
    Workday search results show only a bare city ("Madrid"), but each posting's
    detail record names its country. Returns e.g. "Spain", or None if unknown.
    """
    m = re.match(r"https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)", url)
    if not m:
        return None
    host, site, path = m.groups()
    try:
        info = requests.get(f"https://{host}/wday/cxs/{host.split('.')[0]}/{site}{path}", timeout=8).json().get("jobPostingInfo", {})
    except Exception:
        return None
    if any(_us_state_codes(", " + str(loc)) or US_EXPLICIT_RE.search(str(loc)) for loc in info.get("additionalLocations") or []):
        return "United States of America"  # primary office abroad, but also offered in the US
    country = (info.get("country") or {}).get("descriptor")
    if not country:
        # Some postings leave "country" empty and only fill in the requisition location
        country = (((info.get("jobRequisitionLocation") or {}).get("country")) or {}).get("descriptor")
    return country

def _lever_country(url: str) -> Optional[str]:
    """Lever's board page sometimes shows no location; the posting's own record has a country code."""
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]+)", url)
    if not m:
        return None
    try:
        data = requests.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}?mode=json", timeout=8).json()
    except Exception:
        return None
    code = (data.get("country") or "").upper()
    return "United States" if code == "US" else (code or None)

def _posting_country(url: str) -> Optional[str]:
    if "myworkdayjobs.com" in url:
        return _workday_country(url)
    if "jobs.lever.co" in url:
        return _lever_country(url)
    return None

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
            if country and country != "US" and not loc.get("remote"):
                continue  # SmartRecruiters gives a country code; skip non-US roles outright
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

    candidates = []
    for (board, company), postings in zip(watchlist.items(), results):
        for p in postings:
            title = p["title"]
            if not RELEVANT_TITLE_RE.search(title) or INTERN_RE.search(title) or NON_TECHNICAL_RE.search(title) or SENIOR_LEVEL_RE.search(title) or NON_US_TITLE_RE.search(title):
                continue
            if p["posted"] and p["posted"] < cutoff:
                continue
            us_ok = (not NON_US_RE.search(p["location"])) if p.get("location_unverified") else _is_us_location(p["location"])
            if not us_ok:
                continue
            age = f"{(datetime.now(timezone.utc) - p['posted']).days}d" if p["posted"] else ""
            p["company"], p["age"] = company, age
            candidates.append(p)

    # Workday postings (and Lever ones with no location) get their country checked
    # on the posting itself, once each:
    # results (including rejected non-US postings) are cached between fetches.
    try:
        country_cache = json.loads(WORKDAY_COUNTRY_CACHE.read_text())
    except Exception:
        country_cache = {}
    unverified = [
        p for p in candidates
        if p.get("location_unverified") and p["url"] not in country_cache and normalize_url(p["url"]) not in tracked_jobs
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for p, country in zip(unverified, executor.map(lambda p: _posting_country(p["url"]), unverified)):
            if country:
                country_cache[p["url"]] = country
    try:
        WORKDAY_COUNTRY_CACHE.write_text(json.dumps(country_cache, indent=1, sort_keys=True))
    except OSError as e:
        logger.warning(f"Could not save Workday country cache: {e}")

    jobs = []
    for p in candidates:
        country = country_cache.get(p["url"])
        if country and not _is_us_country(country):
            continue
        jobs.append({
            "normalized_url": normalize_url(p["url"]),
            "url": p["url"],
            "company": p["company"],
            "title": p["title"].strip(),
            "location": p["location"] or "Unknown",
            "repository": REPOSITORY,
            "source": REPOSITORY,
            "category": "All Roles",
            "salary": p["salary"],
            "age": p["age"],
            "status": "new",
        })
    logger.info(f"Found {len(jobs)} relevant postings on company boards.")
    return jobs
