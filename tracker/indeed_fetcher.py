import logging
import time
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict

from .normalizer import normalize_url

logger = logging.getLogger('JobTracker')

# Title variations – same list as the LinkedIn fetcher for consistency
TITLE_VARIATIONS = [
    "AI Engineer",
    "Artificial Intelligence Engineer",
    "Machine Learning Engineer",
    "ML Engineer",
    "AI Research Scientist",
    "Research Scientist (AI)",
    "Senior AI Engineer",
    "Junior AI Engineer",
    "Software Engineer (AI)",
    "Software Engineer – Machine Learning",
    "Backend Engineer – AI",
    "Full-Stack Engineer (AI)",
    "Data Engineer – AI",
    "Applied AI Engineer",
    "Computer Vision Engineer",
    "Natural Language Processing Engineer",
    "Deep Learning Engineer",
    "Data Scientist – AI",
    "Machine Intelligence Engineer",
    "Research Engineer – AI",
    "AI Solutions Engineer",
    "AI Platform Engineer",
    "AI Product Engineer",
    "AI Systems Engineer",
    "AI Software Engineer",
    "AI Specialist",
    "AI Architect",
    "AI Analyst",
    "AI Integration Engineer",
]


def _fetch_rss_for_title(title: str) -> List[Dict]:
    """Fetch the Indeed RSS feed for a given title (remote US) and return job dicts.

    Indeed's public RSS endpoint format:
        https://www.indeed.com/rss?q=<title>&l=Remote+United+States
    """
    query = title.replace(' ', '+')
    rss_url = f"https://www.indeed.com/rss?q={query}&l=Remote+United+States"
    try:
        resp = requests.get(rss_url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch Indeed RSS for '{title}': {e}")
        return []

    jobs: List[Dict] = []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.error(f"Failed to parse Indeed RSS XML for '{title}': {e}")
        return []

    for item in root.findall('.//item'):
        try:
            link_elem = item.find('link')
            title_elem = item.find('title')
            if link_elem is None or title_elem is None:
                continue
            url = link_elem.text.strip()
            job_title = title_elem.text.strip()
            company = ''
            location = 'Remote, United States'
            job = {
                "normalized_url": normalize_url(url),
                "url": url,
                "company": company,
                "title": job_title,
                "location": location,
                "repository": "indeed",
                "source": "indeed",
                "category": "Other",
                "salary": "",
                "age": "",
                "date_first_seen": None,
                "date_opened": None,
                "status": "new",
            }
            jobs.append(job)
        except Exception as e:
            logger.debug(f"Error parsing an Indeed RSS item: {e}")
    return jobs


def fetch_indeed_jobs() -> List[Dict]:
    """Public entry point used by the fetch pipeline.

    Returns a list of job dictionaries from Indeed for the configured title
    variations. No authentication is required.
    """
    all_jobs: List[Dict] = []
    for title in TITLE_VARIATIONS:
        jobs = _fetch_rss_for_title(title)
        logger.debug(f"Fetched {len(jobs)} Indeed jobs for title '{title}'.")
        all_jobs.extend(jobs)
        time.sleep(7.5)
    return all_jobs
