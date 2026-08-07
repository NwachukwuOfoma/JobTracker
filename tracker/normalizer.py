import re
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from typing import List, Dict, Any, Set
from tracker.config import setup_logging

logger = setup_logging()

# Tracking parameters to strip
TRACKING_PARAMS = {
    "gh_src",
    "gh_jid",
    "gh_src_id",
    "ref",
    "source"
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
            
        path = parsed.path
        
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
