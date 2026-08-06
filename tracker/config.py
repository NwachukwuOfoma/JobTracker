import os
import logging
from pathlib import Path
from datetime import datetime

# Base Directory of the application
BASE_DIR = Path(__file__).resolve().parent.parent

# Cache and Logs directories
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
CACHE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Database path
DB_PATH = BASE_DIR / "applied.db"

# Repository URLs
REPO_1_URL = "https://raw.githubusercontent.com/speedyapply/2027-AI-College-Jobs/main/NEW_GRAD_USA.md"
REPO_2_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"
REPO_3_URL = "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md"

# Chrome history default path on macOS
CHROME_HISTORY_PATH = Path(os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/History"))

def setup_logging() -> logging.Logger:
    """Sets up standard and file logging."""
    logger = logging.getLogger("JobTracker")
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console Handler
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)
    c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    c_handler.setFormatter(c_format)
    logger.addHandler(c_handler)

    # File Handler (timestamped log file)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"jobtracker_{timestamp}.log"
    f_handler = logging.FileHandler(log_file, encoding="utf-8")
    f_handler.setLevel(logging.DEBUG)
    f_format = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    f_handler.setFormatter(f_format)
    logger.addHandler(f_handler)

    logger.debug(f"Logging initialized. Log file: {log_file}")
    return logger
