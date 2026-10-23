import logging
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Set, Optional
from bs4 import BeautifulSoup

from .normalizer import normalize_url

logger = logging.getLogger("JobTracker")

TITLE_VARIATIONS = [
    "AI Engineer",
    "Artificial Intelligence Engineer",
    "Machine Learning Engineer",
    "ML Engineer",
    "AI Research Scientist",
    "Research Scientist",
    "Junior AI Engineer",
    "Associate AI Engineer",
    "Entry Level AI Engineer",
    "Software Engineer AI",
    "Software Engineer Machine Learning",
    "Applied AI Engineer",
    "Computer Vision Engineer",
    "Deep Learning Engineer",
    "Data Scientist AI",
    "AI Solutions Engineer",
    "AI Platform Engineer",
    "AI Product Engineer",
    "AI Systems Engineer",
    "AI Software Engineer",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _fetch_linkedin_for_title(title: str, max_pages: int = 3, known_urls: Optional[Set[str]] = None) -> List[Dict]:
    """
    Fetches real jobs from LinkedIn's public endpoint.
    No login required, completely avoiding login bot detection and CAPTCHAs.
    Results are sorted newest-first, so paging stops as soon as a page contains
    nothing that isn't already in known_urls.
    """
    known_urls = known_urls or set()
    jobs = []
    page = 0
    retries = 0
    while page < max_pages:
        start = page * 25
        params = {
            "keywords": title,
            "location": "United States",
            "start": str(start),
            "f_TPR": "r2592000",  # past month (30 days)
            "sortBy": "DD",  # most recent first
        }
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read()
            
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("li")
            if not cards:
                break

            page_new = 0
            for card in cards:
                try:
                    title_elem = card.find("h3", class_="base-search-card__title")
                    company_elem = card.find("h4", class_="base-search-card__subtitle")
                    loc_elem = card.find("span", class_="job-search-card__location")
                    link_elem = card.find("a", class_="base-card__full-link")
                    time_elem = card.find("time")
                    
                    if not link_elem or not title_elem:
                        continue
                        
                    raw_url = link_elem.get("href", "").split("?")[0]
                    company = company_elem.text.strip() if company_elem else "Unknown"
                    job_title = title_elem.text.strip() if title_elem else title
                    loc = loc_elem.text.strip() if loc_elem else "United States"
                    age = time_elem.text.strip() if time_elem else ""
                    
                    norm_url = normalize_url(raw_url)
                    if norm_url not in known_urls:
                        page_new += 1
                    jobs.append({
                        "normalized_url": norm_url,
                        "url": raw_url,
                        "company": company,
                        "title": job_title,
                        "location": loc,
                        "repository": "linkedin",
                        "source": "linkedin",
                        "category": "Other",
                        "salary": "",
                        "age": age,
                        "status": "new"
                    })
                except Exception as ex:
                    logger.debug(f"Error parsing LinkedIn card: {ex}")

            if page_new == 0:
                break  # everything on this page is already known; older pages will be too
            page += 1
            time.sleep(1.0)
        except Exception as e:
            logger.warning(f"Error fetching LinkedIn for '{title}': {e}")
            if ("429" in str(e) or "Too Many Requests" in str(e)) and retries < 2:
                retries += 1
                time.sleep(5 * retries)
                continue  # rate limited: back off and retry the same page
            page += 1
            
    return jobs

def fetch_linkedin_jobs(max_workers: int = 2) -> List[Dict]:
    """Fetches LinkedIn jobs for configured titles, a few titles at a time."""
    logger.info("Starting LinkedIn public job fetch...")
    from .database import get_tracked_jobs
    known_urls = set(get_tracked_jobs().keys())

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(
            lambda t: _fetch_linkedin_for_title(t, max_pages=3, known_urls=known_urls),
            TITLE_VARIATIONS,
        ))

    all_jobs = []
    seen_urls = set()
    for jobs in results:
        for j in jobs:
            if j["normalized_url"] not in seen_urls:
                seen_urls.add(j["normalized_url"])
                all_jobs.append(j)

    logger.info(f"Finished LinkedIn fetch: retrieved {len(all_jobs)} unique listings.")
    return all_jobs
