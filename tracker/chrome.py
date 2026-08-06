import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Set
from tracker.config import CHROME_HISTORY_PATH, setup_logging

logger = setup_logging()

def get_chrome_history_urls(custom_path: Path = None) -> Set[str]:
    """
    Locates, copies, and extracts all visited URLs from ALL Google Chrome profiles.
    """
    urls = set()
    history_paths = []
    
    if custom_path:
        history_paths.append(custom_path)
    else:
        # Standard default path
        if CHROME_HISTORY_PATH.exists():
            history_paths.append(CHROME_HISTORY_PATH)
        
        # Scan parent folder for alternative profiles (e.g. Profile 1, Profile 2, etc.)
        chrome_dir = CHROME_HISTORY_PATH.parent.parent
        if chrome_dir.exists():
            for p in chrome_dir.iterdir():
                if p.is_dir():
                    history_file = p / "History"
                    if history_file.exists() and history_file not in history_paths:
                        history_paths.append(history_file)
                        
    if not history_paths:
        logger.error("No Google Chrome history database found.")
        return urls
        
    logger.info(f"Scanning Chrome history from {len(history_paths)} profile(s)...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, history_path in enumerate(history_paths):
            logger.info(f"Reading Chrome history profile: {history_path.parent.name}")
            temp_db_path = Path(temp_dir) / f"History_temp_{idx}"
            try:
                shutil.copy2(history_path, temp_db_path)
                conn = sqlite3.connect(f"file:{temp_db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM urls")
                profile_count = 0
                for row in cursor.fetchall():
                    url = row[0]
                    if url:
                        urls.add(url)
                        profile_count += 1
                cursor.close()
                conn.close()
                logger.debug(f"Loaded {profile_count} URLs from profile {history_path.parent.name}")
            except Exception as e:
                logger.error(f"Error reading Chrome history database at {history_path}: {e}")
                
    logger.info(f"Successfully loaded a total of {len(urls)} distinct URLs from all Chrome profiles.")
    return urls
