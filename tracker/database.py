import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from tracker.config import DB_PATH, setup_logging

logger = setup_logging()

def init_db(db_path: Path = DB_PATH) -> None:
    """Initializes the SQLite database and creates the jobs table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            normalized_url TEXT PRIMARY KEY,
            original_url TEXT NOT NULL,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            location TEXT NOT NULL,
            repository TEXT NOT NULL,
            category TEXT,
            salary TEXT,
            age TEXT,
            date_first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_opened TIMESTAMP,
            status TEXT NOT NULL CHECK(status IN ('new', 'opened', 'applied', 'skipped'))
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

def get_tracked_jobs(db_path: Path = DB_PATH) -> Dict[str, Dict[str, Any]]:
    """Loads all tracked jobs from the database and returns them as a dictionary keyed by normalized_url."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    
    tracked_jobs = {}
    for row in rows:
        job = dict(row)
        tracked_jobs[job["normalized_url"]] = job
        
    conn.close()
    return tracked_jobs

def insert_jobs(jobs: List[Dict[str, Any]], db_path: Path = DB_PATH) -> None:
    """Inserts a list of jobs into the database."""
    if not jobs:
        return
        
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    
    for job in jobs:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO jobs (
                    normalized_url, original_url, company, title, location, repository, category, salary, age, date_first_seen, date_opened, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job["normalized_url"],
                job["url"],
                job["company"],
                job["title"],
                job["location"],
                job["repository"],
                job.get("category", "Other"),
                job.get("salary", ""),
                job.get("age", ""),
                job.get("date_first_seen", now_str),
                job.get("date_opened"),
                job.get("status", "new")
            ))
        except Exception as e:
            logger.error(f"Error inserting job {job.get('url')}: {e}")
            
    conn.commit()
    conn.close()

def update_job_status(normalized_url: str, status: str, date_opened: Optional[str] = None, db_path: Path = DB_PATH) -> None:
    """Updates the status and optional date_opened of a job."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if date_opened:
        cursor.execute("""
            UPDATE jobs 
            SET status = ?, date_opened = ?
            WHERE normalized_url = ?
        """, (status, date_opened, normalized_url))
    else:
        cursor.execute("""
            UPDATE jobs 
            SET status = ?
            WHERE normalized_url = ?
        """, (status, normalized_url))
        
    conn.commit()
    conn.close()

def update_jobs_status_bulk(normalized_urls: List[str], status: str, mark_opened: bool = False, db_path: Path = DB_PATH) -> None:
    """Updates the status of multiple jobs in bulk."""
    if not normalized_urls:
        return
        
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    
    if mark_opened:
        cursor.executemany("""
            UPDATE jobs 
            SET status = ?, date_opened = ?
            WHERE normalized_url = ?
        """, [(status, now_str, url) for url in normalized_urls])
    else:
        cursor.executemany("""
            UPDATE jobs 
            SET status = ?
            WHERE normalized_url = ?
        """, [(status, url) for url in normalized_urls])
        
    conn.commit()
    conn.close()

def update_job_salary(normalized_url: str, salary: str, db_path: Path = DB_PATH) -> None:
    """Updates the salary of a job in the database."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE jobs 
        SET salary = ?
        WHERE normalized_url = ?
    """, (salary, normalized_url))
    conn.commit()
    conn.close()
