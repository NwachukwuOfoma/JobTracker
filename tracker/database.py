import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from tracker.config import DB_PATH, setup_logging
from tracker.normalizer import annualize_salary

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
            status TEXT NOT NULL CHECK(status IN ('new', 'opened', 'applied', 'skipped')),
            source TEXT NOT NULL DEFAULT 'github'
        )
    """)
    # Auto-migrate any missing columns if table already existed
    cursor.execute("PRAGMA table_info(jobs)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "source" not in existing_cols:
        cursor.execute("ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'github'")
    if "apply_url" not in existing_cols:
        cursor.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT")
    if "duplicate_of" not in existing_cols:
        cursor.execute("ALTER TABLE jobs ADD COLUMN duplicate_of TEXT")
    if "ai_salary_checked" not in existing_cols:
        cursor.execute("ALTER TABLE jobs ADD COLUMN ai_salary_checked INTEGER")
    for col in ("fit_score INTEGER", "fit_note TEXT", "fit_flags TEXT", "fit_resume_hash TEXT"):
        if col.split()[0] not in existing_cols:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
    # Descriptions live in their own table so loading every job stays light
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_descriptions (
            normalized_url TEXT PRIMARY KEY,
            description TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

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
                    normalized_url, original_url, company, title, location, repository, category, salary, age, date_first_seen, date_opened, status, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job["normalized_url"],
                job["url"],
                job["company"],
                job["title"],
                job["location"],
                job["repository"],
                job.get("category", "Other"),
                annualize_salary(job.get("salary", "")),
                job.get("age", ""),
                job.get("date_first_seen", now_str),
                job.get("date_opened"),
                job.get("status", "new"),
                job.get("source", "github")
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
    """, (annualize_salary(salary), normalized_url))
    conn.commit()
    conn.close()

def update_jobs_salary_bulk(normalized_salary: Dict[str, str], db_path: Path = DB_PATH) -> None:
    """Updates the salary for multiple jobs at once.

    Only upserts when the incoming salary is non-empty, so a transient failed
    fetch never wipes out a salary that was previously collected.
    """
    if not normalized_salary:
        return

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    payload = [(annualize_salary(sal), url) for url, sal in normalized_salary.items() if sal and sal.strip()]
    payload = [(sal, url) for sal, url in payload if sal]
    if not payload:
        conn.close()
        return

    cursor.executemany("""
        UPDATE jobs
        SET salary = ?
        WHERE normalized_url = ?
    """, payload)

    conn.commit()
    conn.close()

def update_jobs_apply_url_bulk(apply_urls: Dict[str, str], db_path: Path = DB_PATH) -> None:
    """Stores the employer's direct application link for jobs found via an aggregator (e.g. LinkedIn)."""
    if not apply_urls:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "UPDATE jobs SET apply_url = ? WHERE normalized_url = ?",
        [(url, norm) for norm, url in apply_urls.items()],
    )
    conn.commit()
    conn.close()

def mark_jobs_duplicate(duplicates: Dict[str, str], db_path: Path = DB_PATH) -> None:
    """Skips each job in {duplicate_url: kept_url}, remembering which job it duplicates."""
    if not duplicates:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "UPDATE jobs SET status = 'skipped', duplicate_of = ? WHERE normalized_url = ?",
        [(kept, dup) for dup, kept in duplicates.items()],
    )
    conn.commit()
    conn.close()

def update_jobs_location_bulk(locations: Dict[str, str], db_path: Path = DB_PATH) -> None:
    """Sets the location for multiple jobs, keyed by normalized_url."""
    if not locations:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "UPDATE jobs SET location = ? WHERE normalized_url = ?",
        [(loc, url) for url, loc in locations.items()],
    )
    conn.commit()
    conn.close()

def mark_ai_salary_checked(normalized_urls: List[str], db_path: Path = DB_PATH) -> None:
    """Records that an AI salary lookup ran for these jobs, so each job is only looked up once."""
    if not normalized_urls:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany("UPDATE jobs SET ai_salary_checked = 1 WHERE normalized_url = ?", [(u,) for u in normalized_urls])
    conn.commit()
    conn.close()

def get_job_descriptions(normalized_urls: List[str], db_path: Path = DB_PATH) -> Dict[str, str]:
    """Returns {normalized_url: description} for the jobs whose description has been saved."""
    if not normalized_urls:
        return {}
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    found = {}
    for i in range(0, len(normalized_urls), 500):
        chunk = normalized_urls[i:i + 500]
        rows = conn.execute(
            f"SELECT normalized_url, description FROM job_descriptions WHERE normalized_url IN ({','.join('?' * len(chunk))})",
            chunk,
        ).fetchall()
        found.update(dict(rows))
    conn.close()
    return found

def save_job_descriptions(descriptions: Dict[str, str], db_path: Path = DB_PATH) -> None:
    if not descriptions:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany("INSERT OR REPLACE INTO job_descriptions VALUES (?, ?)", list(descriptions.items()))
    conn.commit()
    conn.close()

def update_jobs_fit_bulk(fits: Dict[str, Dict[str, Any]], resume_hash: str, db_path: Path = DB_PATH) -> None:
    """Saves fit scores ({url: {"score", "note", "flags"}}) and which resume version they were scored against."""
    if not fits:
        return
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "UPDATE jobs SET fit_score = ?, fit_note = ?, fit_flags = ?, fit_resume_hash = ? WHERE normalized_url = ?",
        [(f["score"], f["note"], "; ".join(f["flags"]), resume_hash, url) for url, f in fits.items()],
    )
    conn.commit()
    conn.close()
