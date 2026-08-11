import os
import re
import time
import json
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from tracker.config import (
    CACHE_DIR, REPO_1_URL, REPO_2_URL, REPO_3_URL, setup_logging
)
from tracker.normalizer import normalize_url

logger = setup_logging()

# Cache duration in seconds (e.g., 6 hours)
CACHE_DURATION = 6 * 3600

# Keywords to match US presence or remote status
US_KEYWORDS = {
    "us", "usa", "united states", "remote", "sf", "nyc", "la", "ny", "ca", "tx", "wa", 
    "ma", "va", "co", "or", "il", "pa", "ga", "nj", "fl", "nc", "md", "az", "in", "ks", 
    "mi", "tn", "ut", "oh", "ia", "seattle", "austin", "chicago", "boston", "denver", 
    "atlanta", "new york", "san francisco", "los angeles", "palo alto", "redmond", 
    "cupertino", "sunnyvale", "mountain view", "san jose"
}

def is_us_or_remote(location: str) -> bool:
    """Returns True if the location is remote or has a US presence."""
    if not location:
        return True  # Keep if empty
    loc_lower = location.lower()
    # Tokenize words/abbreviations
    tokens = re.findall(r'[a-z0-9]+', loc_lower)
    return any(t in US_KEYWORDS for t in tokens)

def is_phd_exclusive(title: str) -> bool:
    """Returns True if the job title indicates it is exclusively for PhD candidates."""
    title_lower = title.lower()
    if "phd" in title_lower or "ph.d" in title_lower:
        # If it also lists standard undergrad/grad degrees, it is not exclusive
        if any(kw in title_lower for kw in ["bs", "ms", "bachelor", "master", "undergrad"]):
            return False
        return True
    return False

def clean_html_text(html_str: str) -> str:
    """Helper to strip HTML tags and extra whitespace from a string."""
    if not html_str:
        return ""
    # Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', ' ', html_str)
    # Replace multiple spaces/newlines with single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    # Strip emojis and leading/trailing markers like 🔥 or ↳
    cleaned = cleaned.replace("🔥", "").replace("↳", "").strip()
    return cleaned

def extract_link_from_html(html_str: str) -> str:
    """Extracts the first href URL from an HTML snippet."""
    if not html_str:
        return ""
    soup = BeautifulSoup(html_str, "html.parser")
    a_tag = soup.find("a")
    if a_tag and a_tag.get("href"):
        return a_tag.get("href").strip()
    return ""

def fetch_salary_from_url(url: str) -> str:
    """Attempts to crawl the target URL and search its text for salary ranges (USD)."""
    if not url or not url.startswith("http"):
        return ""
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*"
    }
    
    try:
        # Helper to extract JSON-LD structured salary or description text
        json_ld_salary = ""
        json_ld_desc = ""
        
        # 1. Handle Workday Single Page Application URLs (general structure)
        if "myworkdayjobs.com" in url:
            # Convert: https://{subdomain}.myworkdayjobs.com/{folders}/job/{job_path}
            # To API: https://{subdomain}.myworkdayjobs.com/wday/cxs/{tenant}/{rb}/job/{job_path}
            workday_match = re.match(r'https://([^/]+)\.myworkdayjobs\.com/(.+)/job/(.+)', url)
            if workday_match:
                subdomain, prefix_folders, job_path = workday_match.groups()
                tenant = subdomain.split('.')[0]
                folders = prefix_folders.split('/')
                rb = folders[-1].lower()
                api_url = f"https://{subdomain}.myworkdayjobs.com/wday/cxs/{tenant}/{rb}/job/{job_path}"
                response = requests.get(api_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    desc_html = data.get("jobPostingInfo", {}).get("jobDescription", "")
                    if desc_html:
                        # Parse HTML description in JSON
                        soup = BeautifulSoup(desc_html, "html.parser")
                        text = soup.get_text(" ")
                    else:
                        text = json.dumps(data)
                elif response.status_code in (400, 403, 404, 410, 422):
                    return "__DEAD__"
                else:
                    return ""
            else:
                return ""
        elif "workable.com" in url:
            # Convert: https://apply.workable.com/{account_slug}/j/{shortcode}/
            # To API: https://apply.workable.com/api/v2/accounts/{account_slug}/jobs/{shortcode}
            workable_match = re.match(r'https://apply\.workable\.com/([^/]+)/j/([^/]+)', url)
            if workable_match:
                account_slug, shortcode = workable_match.groups()
                shortcode = shortcode.split('/')[0]
                api_url = f"https://apply.workable.com/api/v2/accounts/{account_slug}/jobs/{shortcode}"
                response = requests.get(api_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    desc_html = data.get("description", "") + " " + data.get("requirements", "") + " " + data.get("benefits", "")
                    if desc_html:
                        soup = BeautifulSoup(desc_html, "html.parser")
                        text = soup.get_text(" ")
                    else:
                        text = json.dumps(data)
                elif response.status_code in (400, 403, 404, 410, 422):
                    return "__DEAD__"
                else:
                    return ""
            else:
                return ""
        elif "gh_jid=" in url:
            # Handle Greenhouse embedded jobs (e.g. mthree)
            gh_jid_match = re.search(r'[?&]gh_jid=([0-9]+)', url)
            if gh_jid_match:
                response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    token_match = re.search(r'greenhouse\.io/embed/job_board/[^?]+\?for=([^"\'&>]+)', response.text)
                    if token_match:
                        board_token = token_match.group(1).strip()
                        job_id = gh_jid_match.group(1).strip()
                        api_url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
                        api_res = requests.get(api_url, headers=headers, timeout=5)
                        if api_res.status_code == 200:
                            import html
                            data = api_res.json()
                            desc_html = html.unescape(data.get("content", ""))
                            soup = BeautifulSoup(desc_html, "html.parser")
                            text = soup.get_text(" ")
                        else:
                            text = ""
                    else:
                        text = ""
                else:
                    text = ""
            else:
                text = ""
        elif "/careers/job/" in url:
            # Handle Eightfold job listings (e.g. Microsoft)
            eightfold_match = re.search(r'https?://([^/]+)/careers/job/([0-9]+)', url)
            if eightfold_match:
                domain, job_id = eightfold_match.groups()
                api_url = f"https://{domain}/api/apply/v2/jobs/{job_id}"
                api_res = requests.get(api_url, headers=headers, timeout=5)
                if api_res.status_code == 200:
                    data = api_res.json()
                    desc_html = data.get("job_description", "")
                    if desc_html:
                        soup = BeautifulSoup(desc_html, "html.parser")
                        text = soup.get_text(" ")
                    else:
                        text = ""
                elif api_res.status_code in (400, 403, 404, 410, 422):
                    return "__DEAD__"
                else:
                    text = ""
            else:
                text = ""
        else:
            # 3. Standard HTML Pages (Greenhouse, Lever, Ashby, etc.)
            response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
            if response.status_code in (404, 410):
                return "__DEAD__"
            elif response.status_code != 200:
                return ""
                
            # Parse JSON-LD Schema if present BEFORE decomposing script tags!
            soup_pre = BeautifulSoup(response.text, "html.parser")
            for s in soup_pre.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(s.string or s.text or "{}")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") == "JobPosting" or "baseSalary" in item:
                            # 1. Check for structured baseSalary
                            base_salary = item.get("baseSalary")
                            if base_salary and isinstance(base_salary, dict):
                                val_data = base_salary.get("value")
                                if val_data and isinstance(val_data, dict):
                                    min_v = val_data.get("minValue")
                                    max_v = val_data.get("maxValue")
                                    unit = val_data.get("unitText", "YEAR").upper()
                                    if min_v is not None and max_v is not None:
                                        suffix = " / hr" if "HOUR" in unit or "HR" in unit else ""
                                        min_fmt = f"${min_v:,}" if isinstance(min_v, (int, float)) else f"${min_v}"
                                        max_fmt = f"${max_v:,}" if isinstance(max_v, (int, float)) else f"${max_v}"
                                        if min_fmt.endswith(".0"): min_fmt = min_fmt[:-2]
                                        if max_fmt.endswith(".0"): max_fmt = max_fmt[:-2]
                                        json_ld_salary = f"{min_fmt} - {max_fmt}{suffix}"
                            # 2. Extract description HTML for fallback text search
                            desc_html = item.get("description", "")
                            if desc_html:
                                json_ld_desc = BeautifulSoup(desc_html, "html.parser").get_text(" ")
                except Exception:
                    continue
            
            # If we found a structured salary from JSON-LD, return it immediately!
            if json_ld_salary:
                return json_ld_salary
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Strip script/style components
            for tag in soup(["script", "style", "meta", "link", "noscript"]):
                tag.decompose()
                
            text = soup.get_text(" ") + " " + json_ld_desc
        
        # Look for USD salary ranges in text
        # Regex 1: Hourly ranges (e.g. $35.00 - $50.00 / hr or $60-$90 per hour)
        hourly_match = re.search(r'\$\s*[0-9]+(?:\.[0-9]+)?\s*(?:-|to|–|—)\s*\$\s*[0-9]+(?:\.[0-9]+)?\s*(?:/|per)\s*(?:hr|hour)', text, re.IGNORECASE)
        if hourly_match:
            return hourly_match.group(0).strip()

        # Regex 2: Context-based range with optional $ and optional USD (e.g. salary range is 116,000 - 189,750 or Salary: 70,880 - 106,200)
        context_match = re.search(
            r'(?:salary|pay|compensation|scale|base)\s*(?:range|rate|pay)?\s*(?::)?\s*(?:is|of)?\s*(?:between)?\s*(?:usd)?\s*(\$?\s*[0-9,]+(?:\.[0-9]+)?\s*(?:usd)?)\s*(?:-|to|–|—)\s*(?:usd)?\s*(\$?\s*[0-9,]+(?:\.[0-9]+)?\s*(?:usd)?)',
            text,
            re.IGNORECASE
        )
        if context_match:
            # Format nicely
            val1 = context_match.group(1).strip()
            val2 = context_match.group(2).strip()
            
            def clean_val(v):
                v_clean = v.lower().replace(",", "").replace(".", "").replace("usd", "").strip()
                if not v.startswith("$") and v_clean.isdigit():
                    return f"${v.upper()}"
                return v.upper()
                
            val1 = clean_val(val1)
            val2 = clean_val(val2)
            return f"{val1} - {val2}"

        # Regex 3: Standard dollar-sign numeric ranges (e.g. $67,500.00 - $112,500.00 or $ 205,000 - $ 230,000)
        range_match = re.search(r'\$\s*[0-9,]+(?:\.[0-9]+)?\s*(?:-|to|–|—)\s*\$\s*[0-9,]+(?:\.[0-9]+)?', text)
        if range_match:
            return range_match.group(0).strip()
            
        # Regex 4: USD suffix numeric ranges (e.g. 116,000 USD - 189,750 USD)
        usd_range_match = re.search(r'\$?\s*[0-9,]+(?:\.[0-9]+)?\s*(?:usd)?\s*(?:-|to|–|—)\s*\$?\s*[0-9,]+(?:\.[0-9]+)?\s*usd', text, re.IGNORECASE)
        if usd_range_match:
            val = usd_range_match.group(0).strip()
            if not val.startswith("$"):
                val = f"${val}"
            return val
            
        # Regex 5: Abbreviated ranges (e.g. $100k - $150k or $151.3K – $178K)
        abbrev_match = re.search(r'\$\s*[0-9]+(?:\.[0-9]+)?k\s*(?:-|to|–|—)\s*\$\s*[0-9]+(?:\.[0-9]+)?k', text, re.IGNORECASE)
        if abbrev_match:
            return abbrev_match.group(0).strip()
            
        # Regex 6: Single figures (e.g. $100,000)
        single_match = re.search(r'\$\s*[0-9]{2,3},[0-9]{3}(?:\.[0-9]+)?', text)
        if single_match:
            return single_match.group(0).strip() + " (Est.)"
            
    except Exception as e:
        logger.debug(f"Failed to fetch salary from external link '{url}': {e}")
        
    return ""

def fetch_repository_content(url: str, filename: str, force_refresh: bool = False) -> str:
    """
    Downloads repository content from the given URL.
    Uses local cache if file is fresh, unless force_refresh is True.
    """
    cache_path = CACHE_DIR / filename
    
    if not force_refresh and cache_path.exists():
        file_age = time.time() - cache_path.stat().st_mtime
        if file_age < CACHE_DURATION:
            logger.info(f"Using cached file for {filename} (age: {file_age / 60:.1f} mins).")
            with open(cache_path, "r", encoding="utf-8") as f:
                return f.read()
                
    logger.info(f"Downloading latest markdown from: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        content = response.text
        
        # Save to cache
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return content
    except Exception as e:
        logger.error(f"Failed to download from {url}: {e}")
        if cache_path.exists():
            logger.warning(f"Falling back to stale cache for {filename}.")
            with open(cache_path, "r", encoding="utf-8") as f:
                return f.read()
        raise e

def parse_repo_1_and_3(markdown_content: str, repo_name: str) -> List[Dict[str, Any]]:
    """
    Parses Repo 1 and Repo 3 markdown tables.
    Columns: | Company | Position | Location | Salary | Posting | Age |
    """
    jobs = []
    lines = markdown_content.splitlines()
    
    current_category = "Other"
    
    for line in lines:
        line = line.strip()
        
        # Filter 1: Skip if closed/locked
        if "🔒" in line:
            continue
            
        # Check for headings to update the current category
        if line.startswith("###"):
            h_text = line.replace("#", "").strip().lower()
            if "faang" in h_text:
                current_category = "FAANG"
            elif "quant" in h_text or "finance" in h_text:
                current_category = "Finance"
            elif "other" in h_text:
                current_category = "Other"
            continue
            
        if not line.startswith("|") or line.endswith("---|---") or "Company | Position" in line:
            continue
            
        parts = [p.strip() for p in line.split("|")[1:-1]]
        salary = ""
        age = ""
        if len(parts) == 5:
            raw_company, raw_position, raw_location, raw_posting = parts[0], parts[1], parts[2], parts[3]
            age = clean_html_text(parts[4])
        elif len(parts) >= 6:
            raw_company, raw_position, raw_location, raw_posting = parts[0], parts[1], parts[2], parts[4]
            salary = clean_html_text(parts[3])
            age = clean_html_text(parts[5])
        else:
            continue
        
        company = clean_html_text(raw_company)
        title = clean_html_text(raw_position)
        location = clean_html_text(raw_location)
        
        # Filter 2: PhD Exclusive
        if is_phd_exclusive(title):
            continue
            
        # Filter 3: US / Remote Location Only
        if not is_us_or_remote(location):
            continue
            
        # Extract Apply URL
        url = extract_link_from_html(raw_posting)
        if not url:
            # Fallback: maybe it is markdown link [Apply](url) or raw link
            match = re.search(r'href=["\']([^"\']+)["\']', raw_posting)
            if match:
                url = match.group(1)
            else:
                match_md = re.search(r'\[.*?\]\((.*?)\)', raw_posting)
                if match_md:
                    url = match_md.group(1)
                else:
                    url = raw_posting
                    
        if not url or url.startswith("/") or url == "#":
            continue
            
        jobs.append({
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "normalized_url": normalize_url(url),
            "repository": repo_name,
            "category": current_category,
            "salary": salary,
            "age": age,
            "status": "new"
        })
        
    logger.info(f"Parsed {len(jobs)} jobs from {repo_name}.")
    return jobs

def parse_repo_2(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Parses Repo 2, ONLY extracting Software Engineering and Data Science/AI/ML sections.
    """
    jobs = []
    
    # Split content by markdown headers
    swe_header_match = re.search(r'##\s+.*Software\s+Engineering\s+New\s+Grad\s+Roles', markdown_content, re.IGNORECASE)
    ds_header_match = re.search(r'##\s+.*Data\s+Science,\s+AI\s+&\s+Machine\s+Learning\s+New\s+Grad\s+Roles', markdown_content, re.IGNORECASE)
    
    sections = []
    if swe_header_match:
        sections.append(("Software Engineering", swe_header_match.start()))
    if ds_header_match:
        sections.append(("Data Science/AI/ML", ds_header_match.start()))
        
    sections.sort(key=lambda x: x[1])
    
    for i, (sec_name, start_idx) in enumerate(sections):
        end_idx = len(markdown_content)
        next_heading_match = re.search(r'\n##\s+', markdown_content[start_idx + 1:])
        if next_heading_match:
            end_idx = start_idx + 1 + next_heading_match.start()
            
        section_text = markdown_content[start_idx:end_idx]
        
        soup = BeautifulSoup(section_text, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning(f"No HTML table found in Repo 2 section '{sec_name}'.")
            continue
            
        rows = table.find_all("tr")
        last_company = ""
        
        for row in rows:
            # Filter 1: Closed jobs indicated by lock icon in row content
            if "🔒" in str(row):
                continue
                
            cols = row.find_all(["td", "th"])
            if not cols or cols[0].name == "th":
                continue
                
            if len(cols) < 4:
                continue
                
            raw_company = cols[0]
            raw_role = cols[1]
            raw_location = cols[2]
            raw_app = cols[3]
            age = ""
            if len(cols) >= 5:
                age = clean_html_text(str(cols[4]))
            
            # Company name extraction
            company_text = raw_company.get_text().strip()
            if "↳" in company_text or company_text == "↳" or not company_text:
                company = last_company
            else:
                company = clean_html_text(str(raw_company))
                last_company = company
                
            title = clean_html_text(str(raw_role))
            location = clean_html_text(str(raw_location))
            
            # Filter 2: PhD Exclusive
            if is_phd_exclusive(title):
                continue
                
            # Filter 3: US / Remote Location Only
            if not is_us_or_remote(location):
                continue
                
            # The apply URL is the first link in the app column
            url = ""
            a_tags = raw_app.find_all("a")
            for a in a_tags:
                href = a.get("href", "")
                if "simplify.jobs/p/" not in href and href:
                    url = href.strip()
                    break
            
            if not url and a_tags:
                url = a_tags[0].get("href", "").strip()
                
            if not url or url.startswith("/") or url == "#":
                continue
                
            repo_label = (
                "SimplifyJobs-Software Engineering New Grad Roles" 
                if sec_name == "Software Engineering" 
                else "SimplifyJobs-Data Science, AI & Machine Learning New Grad Roles"
            )
            jobs.append({
                "company": company,
                "title": title,
                "location": location,
                "url": url,
                "normalized_url": normalize_url(url),
                "repository": repo_label,
                "category": sec_name,
                "salary": "",
                "age": age,
                "status": "new"
            })
            
    logger.info(f"Parsed {len(jobs)} jobs from SimplifyJobs (New-Grad-Positions).")
    return jobs

def scrape_all_jobs(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Downloads, parses, and aggregates jobs from all three repositories."""
    all_jobs = []
    
    # Repo 1
    try:
        content_1 = fetch_repository_content(REPO_1_URL, "repo_1.md", force_refresh)
        jobs_1 = parse_repo_1_and_3(content_1, "2027-AI-College-Jobs")
        all_jobs.extend(jobs_1)
    except Exception as e:
        logger.error(f"Error processing Repo 1: {e}")
        
    # Repo 2
    try:
        content_2 = fetch_repository_content(REPO_2_URL, "repo_2.md", force_refresh)
        jobs_2 = parse_repo_2(content_2)
        all_jobs.extend(jobs_2)
    except Exception as e:
        logger.error(f"Error processing Repo 2: {e}")
        
    # Repo 3
    try:
        content_3 = fetch_repository_content(REPO_3_URL, "repo_3.md", force_refresh)
        jobs_3 = parse_repo_1_and_3(content_3, "2027-SWE-College-Jobs")
        all_jobs.extend(jobs_3)
    except Exception as e:
        logger.error(f"Error processing Repo 3: {e}")
        
    return all_jobs
