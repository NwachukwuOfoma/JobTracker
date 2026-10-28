import re
import json
from urllib.parse import urlparse, parse_qsl, unquote, urlencode, urlunparse
from typing import List, Dict, Any, Set, Optional, Tuple
from tracker.config import CACHE_DIR, setup_logging

logger = setup_logging()

# Tracking/Layout parameters to strip
TRACKING_PARAMS = {
    "gh_src",
    "gh_jid",
    "gh_src_id",
    "ref",
    "source",
    "embed",
    "iframe",
    "widget",
    "ref_type",
    "click_id",
    "shared_id",
    "jobboard",
    "applicant_source",
    "apply_source",
    "icims"
}

def normalize_url(url: str) -> str:
    """
    Normalizes a URL by converting the scheme to https, lowercasing the host,
    stripping trailing slashes and common application suffixes (like /apply, /resume),
    canonicalizing specific domains (like TikTok/ByteDance), and removing tracking parameters.
    """
    if not url:
        return ""
        
    try:
        url_str = url.strip()
        parsed = urlparse(url_str)
        
        # Standardize scheme (most job sites are https)
        scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme
        
        # Lowercase host
        netloc = parsed.netloc.lower()
        
        # 1. Custom Rule: TikTok / ByteDance
        if any(domain in netloc for domain in ["tiktok", "bytedance"]):
            # Extract the 19-digit Job ID
            id_match = re.search(r'\d{19}', url_str)
            if id_match:
                return f"https://lifeattiktok.com/search/{id_match.group(0)}"
                
        # 2. Custom Rule: Greenhouse Host Normalization
        if "greenhouse.io" in netloc:
            netloc = "boards.greenhouse.io"
            
        path = parsed.path.lower()
        
        # 3. Custom Rule: Strip language/locale prefix path (e.g. /en-US/, /en/, /fr-FR/)
        path = re.sub(r'^/[a-z]{2}(?:-[a-zA-Z]{2})?/', '/', path, flags=re.IGNORECASE)
        
        # Strip trailing action paths
        path = re.sub(r'/(apply|application|detail|resume|apply/|application/|detail/|resume/)$', '', path)
        if path.endswith("/"):
            path = path[:-1]
            
        # Parse and filter query parameters
        query_params = []
        for key, val in parse_qsl(parsed.query):
            key_lower = key.lower()
            # Skip utm_* parameters
            if key_lower.startswith("utm_"):
                continue
            # Skip other tracking parameters
            if key_lower in TRACKING_PARAMS:
                continue
            query_params.append((key, val))
            
        # Reconstruct query string
        query = urlencode(sorted(query_params)) if query_params else ""
        
        # Reconstruct the full normalized URL (without fragment)
        normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))
        return normalized
    except Exception as e:
        logger.warning(f"Failed to normalize URL '{url}': {e}")
        return url.strip()

# Pages a job tab went on to (a LinkedIn job's company site), as tab key -> the job's
# tab key. Kept in cache/, since these URLs are personal browsing
PAGE_LINKS_FILE = CACHE_DIR / "page_links.json"


def load_page_links():
    try:
        return json.loads(PAGE_LINKS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def tab_key(url):
    """normalize_url, made looser for matching open tabs: an apply page carries
    tracking parameters (Lever's lever-source) and encodes commas (Workday's
    "Boulder%2C-CO") that the stored link doesn't. Not for dedupe keys."""
    parsed = urlparse(normalize_url(url))
    path = unquote(parsed.path).replace(",", "")
    query = [(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("lever-") and k not in ("_pc", "src")]
    return urlunparse(parsed._replace(path=path, query=urlencode(query)))


def deduplicate_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates a list of jobs based on their normalized URLs.
    Preserves the first encountered instance of a job.
    """
    seen_normalized: Set[str] = set()
    deduplicated: List[Dict[str, Any]] = []
    
    for job in jobs:
        norm_url = job.get("normalized_url")
        if not norm_url:
            norm_url = normalize_url(job.get("url", ""))
            job["normalized_url"] = norm_url
            
        if norm_url not in seen_normalized:
            seen_normalized.add(norm_url)
            deduplicated.append(job)
        else:
            logger.debug(f"Removing duplicate job for URL: {job.get('url')}")
            
    return deduplicated

HOURS_PER_YEAR = 2080
_ANNUALIZED_MARKER = "/yr (from "
_HOURLY_RE = re.compile(r"\bh(?:ou)?r\b|hourly|/\s*h\b", re.IGNORECASE)

def _classify_salary(salary: str) -> Tuple[List[float], Optional[str]]:
    """
    Extracts the dollar figures from a salary string and decides what unit they're in:
    - "hourly":    an explicit hourly rate ("/hr", "per hour"), or bare numbers under 100
                   ("$18.00 - $20.00")
    - "thousands": bare numbers from 100 to 999, where the "K" was dropped ("$250 - $300")
    - "annual":    anything else ("$130,000 - $150,000", "$168k/yr")
    - None:        empty or placeholder values like "$0.00 - $0.00" or "$1 - $5"
    """
    if not salary:
        return [], None
    text = salary.lower()
    if _ANNUALIZED_MARKER in text:
        text = text.split(_ANNUALIZED_MARKER)[0]  # already annualized; read the annual part
    head = text.split("(")[0]
    if re.search(r"\d,?\d{3}", head):
        text = head  # "$93,600 - $124,800 (Est., from $45/hr)": the note doesn't change the unit
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    values = [float(n) * (1000 if k else 1) for n, k in re.findall(r"(\d+(?:\.\d+)?)\s*(k?)\b", text)]
    if not values or max(values) < 10:
        return values, None
    if _HOURLY_RE.search(text) or max(values) < 100:
        return values, "hourly"
    if max(values) < 1000:
        return values, "thousands"
    return values, "annual"

def parse_annual_salary(salary: str) -> Optional[Tuple[float, float]]:
    """Parses a salary string into an annual (low, high) range in dollars, or None."""
    values, unit = _classify_salary(salary)
    if unit is None:
        return None
    factor = {"hourly": HOURS_PER_YEAR, "thousands": 1000, "annual": 1}[unit]
    return min(values) * factor, max(values) * factor

def annualize_salary(salary: str) -> str:
    """
    Rewrites hourly and "K-less" salaries as an annual range (hourly ones keep the
    original rate for reference). Annual salaries are left untouched, and
    placeholder values become "".
    """
    if not salary or not salary.strip():
        return ""
    if _ANNUALIZED_MARKER in salary:
        return salary
    values, unit = _classify_salary(salary)
    if unit is None:
        return ""
    if unit == "annual":
        return salary
    lo, hi = parse_annual_salary(salary)
    annual = f"${lo:,.0f}" if lo == hi else f"${lo:,.0f} - ${hi:,.0f}"
    if unit == "thousands":
        return annual
    original = salary.strip()
    if not _HOURLY_RE.search(original):
        original += "/hr"
    return f"{annual}{_ANNUALIZED_MARKER}{original})"

def job_identity_key(company: str, title: str) -> Tuple[str, str]:
    """
    A source-independent key for "the same job": the same role posted on LinkedIn
    and on a GitHub board (or once per city on LinkedIn) has different URLs but
    the same company and title. Legal suffixes and punctuation are ignored, so
    "Reddit, Inc." and "Reddit" match.
    """
    company = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company)\b\.?", "", company.lower())
    return re.sub(r"[^a-z0-9]", "", company), re.sub(r"[^a-z0-9]", "", title.lower())
