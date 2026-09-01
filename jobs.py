import sys
import argparse
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor

from tracker.config import DB_PATH, setup_logging
from tracker.chrome import get_chrome_history_urls
from tracker.normalizer import normalize_url, deduplicate_jobs
from tracker.database import (
    init_db, get_tracked_jobs, insert_jobs, 
    update_jobs_status_bulk, update_job_status, update_job_salary
)
from tracker.scraper import scrape_all_jobs, fetch_salary_from_url
from tracker.exporter import generate_csv, generate_html

logger = setup_logging()

def open_urls_in_chrome(urls: List[str]) -> None:
    """Opens a list of URLs in Google Chrome on macOS."""
    if not urls:
        return
    logger.info(f"Opening {len(urls)} URLs in Google Chrome...")
    for url in urls:
        try:
            # Use macOS open command to explicitly target Google Chrome
            subprocess.run(["open", "-a", "Google Chrome", url], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.warning(f"Failed to open in Chrome using subprocess, falling back to webbrowser: {e}")
            webbrowser.open(url)

def parse_range(range_str: str, max_val: int) -> Set[int]:
    """Parses user input range like '1, 2, 4-6' into a set of 0-based indices."""
    indices = set()
    parts = range_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_str, end_str = part.split("-", 1)
                start = int(start_str.strip()) - 1
                end = int(end_str.strip()) - 1
                if 0 <= start <= end < max_val:
                    for idx in range(start, end + 1):
                        indices.add(idx)
            except ValueError:
                pass
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < max_val:
                    indices.add(idx)
            except ValueError:
                pass
    return indices

def run_status_management(target_status: str) -> None:
    """Interactively allows the user to mark 'opened' jobs as applied or skipped."""
    init_db()
    tracked = get_tracked_jobs()
    
    # Filter for jobs with status 'opened'
    opened_jobs = [job for job in tracked.values() if job["status"] == "opened"]
    
    if not opened_jobs:
        print(f"\nNo jobs currently have the status 'opened'. Run --daily or --open first.")
        return
        
    print(f"\n==============================\nOPENED JOBS AVAILABLE TO MARK AS {target_status.upper()}\n==============================")
    for i, job in enumerate(opened_jobs, 1):
        print(f"[{i}] {job['company']} - {job['title']} ({job['repository']})")
        
    print("\nEnter job numbers to update (e.g. '1, 3, 5-8'), 'all' to select all, or press Enter/Ctrl+C to cancel:")
    try:
        user_input = input("> ").strip().lower()
        if not user_input:
            print("Action cancelled.")
            return
            
        selected_indices = set()
        if user_input == "all":
            selected_indices = set(range(len(opened_jobs)))
        else:
            selected_indices = parse_range(user_input, len(opened_jobs))
            
        if not selected_indices:
            print("No valid jobs selected.")
            return
            
        urls_to_update = [opened_jobs[idx]["normalized_url"] for idx in selected_indices]
        update_jobs_status_bulk(urls_to_update, target_status)
        print(f"Successfully marked {len(urls_to_update)} jobs as '{target_status}'.")
        
    except (KeyboardInterrupt, EOFError):
        print("\nAction cancelled.")

def run_export() -> None:
    """Regenerates HTML and CSV from the current state of the database."""
    init_db()
    tracked = get_tracked_jobs()
    interacted_map = {}
    for job in tracked.values():
        if job["status"] in ("applied", "skipped", "opened"):
            key = (job["company"].lower().strip(), job["title"].lower().strip())
            interacted_map[key] = job["status"]

    new_jobs = [
        {
            "company": job["company"],
            "title": job["title"],
            "location": job["location"],
            "repository": job["repository"],
            "category": job.get("category", "Other"),
            "salary": job.get("salary", ""),
            "age": job.get("age", ""),
            "url": job["original_url"],
            "similar_status": interacted_map.get((job["company"].lower().strip(), job["title"].lower().strip()), "")
        }
        for job in tracked.values() if job["status"] == "new"
    ]
    generate_csv(new_jobs)
    generate_html(new_jobs)
    print(f"Export complete. {len(new_jobs)} new jobs exported to CSV/HTML.")

def main() -> None:
    parser = argparse.ArgumentParser(description="JobTracker: Track and manage job applications.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daily", action="store_true", help="Run the daily workflow.")
    group.add_argument("--open", action="store_true", help="Open all current NEW jobs in Chrome.")
    group.add_argument("--export", action="store_true", help="Regenerate HTML and CSV outputs.")
    group.add_argument("--mark-applied", action="store_true", help="Interactive prompt to mark opened jobs as applied.")
    group.add_argument("--mark-skipped", action="store_true", help="Interactive prompt to mark opened jobs as skipped.")
    parser.add_argument("--refresh", "--force-refresh", action="store_true", help="Force redownload of repository markdown files, ignoring the 6-hour cache.")
    args = parser.parse_args()
    
    # Handle status management commands directly
    if args.mark_applied:
        run_status_management("applied")
        return
    if args.mark_skipped:
        run_status_management("skipped")
        return
    if args.export:
        run_export()
        return

    # For normal run and --daily run:
    init_db()
    
    # 1. Scrape jobs from all repositories
    print("Scraping job repositories...")
    scraped_jobs = scrape_all_jobs(force_refresh=args.refresh)
    total_scraped = len(scraped_jobs)
    
    # 2. Deduplicate based on normalized URLs
    deduped_scraped = deduplicate_jobs(scraped_jobs)
    total_removed = total_scraped - len(deduped_scraped)
    
    # 3. Read Chrome History
    chrome_history_urls = get_chrome_history_urls()
    normalized_chrome_urls = {normalize_url(url) for url in chrome_history_urls}
    
    # 4. Read tracked jobs from applied.db
    tracked_jobs = get_tracked_jobs()
    is_first_run = (len(tracked_jobs) == 0)
    
    new_jobs_list = []
    already_visited_list = []
    
    jobs_to_insert = []
    jobs_to_update_status_opened = []
    
    # 5. Classify jobs
    for job in deduped_scraped:
        norm_url = job["normalized_url"]
        
        # Check Chrome History
        in_chrome = norm_url in normalized_chrome_urls
        
        if is_first_run:
            # First run behavior:
            # Initialize applied.db ONLY with jobs confirmed to exist in Chrome History.
            if in_chrome:
                job["status"] = "opened"
                job["date_opened"] = datetime.now().isoformat()
                jobs_to_insert.append(job)
                already_visited_list.append(job)
            else:
                # Do NOT insert to DB on first run if not in Chrome (or we can defer inserting new jobs).
                # But we should still display them as NEW to the user!
                new_jobs_list.append(job)
        else:
            # Subsequent runs:
            # Compare against BOTH Chrome History and applied.db
            if norm_url in tracked_jobs:
                db_job = tracked_jobs[norm_url]
                # If it's in Chrome history but database says 'new', update it to 'opened'
                if in_chrome and db_job["status"] == "new":
                    jobs_to_update_status_opened.append(norm_url)
                    db_job["status"] = "opened"
                    db_job["date_opened"] = datetime.now().isoformat()
                
                # Check status
                if db_job["status"] in ("opened", "applied", "skipped"):
                    already_visited_list.append(job)
                else:
                    new_jobs_list.append(job)
            else:
                # Completely new job (not in DB and not in Chrome History)
                if in_chrome:
                    job["status"] = "opened"
                    job["date_opened"] = datetime.now().isoformat()
                    jobs_to_insert.append(job)
                    already_visited_list.append(job)
                else:
                    # New job not visited yet. Save to db as 'new'.
                    job["status"] = "new"
                    jobs_to_insert.append(job)
                    new_jobs_list.append(job)
                    
    # Investigating missing salaries concurrently
    jobs_needing_salary = [j for j in new_jobs_list if not j.get("salary")]
    dead_urls = []
    if jobs_needing_salary:
        print(f"Investigating {len(jobs_needing_salary)} external links for salary range info...")
        def process_job_salary(job_dict):
            try:
                salary = fetch_salary_from_url(job_dict["url"])
                if salary == "__DEAD__":
                    dead_urls.append(job_dict["normalized_url"])
                elif salary:
                    job_dict["salary"] = salary
                    update_job_salary(job_dict["normalized_url"], salary)
                    logger.info(f"Found salary for {job_dict['company']}: {salary}")
            except Exception as e:
                pass

        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(process_job_salary, jobs_needing_salary))
            
        if dead_urls:
            print(f"Detected {len(dead_urls)} dead/closed job postings. Marking them as skipped.")
            update_jobs_status_bulk(dead_urls, "skipped")
            new_jobs_list = [j for j in new_jobs_list if j["normalized_url"] not in dead_urls]
                     
    # Perform database write operations
    if jobs_to_insert:
        # Filter out dead jobs from initial insert if they were found to be dead during this run
        jobs_to_insert = [j for j in jobs_to_insert if j["normalized_url"] not in dead_urls]
        insert_jobs(jobs_to_insert)
    if jobs_to_update_status_opened:
        jobs_to_update_status_opened = [u for u in jobs_to_update_status_opened if u not in dead_urls]
        update_jobs_status_bulk(jobs_to_update_status_opened, "opened", mark_opened=True)
        
    # Get current statistics from the DB
    updated_tracked = get_tracked_jobs()
    opened_count = sum(1 for j in updated_tracked.values() if j["status"] == "opened")
    applied_count = sum(1 for j in updated_tracked.values() if j["status"] == "applied")
    skipped_count = sum(1 for j in updated_tracked.values() if j["status"] == "skipped")
    
    # Print Stdout Output
    print("\n==============================")
    print("NEW JOBS")
    print("==============================")
    for job in new_jobs_list:
        print(f"\nCompany: {job['company']}")
        print(f"Title: {job['title']}")
        print(f"Location: {job['location']}")
        print(f"Repository: {job['repository']}")
        print(f"Application URL: {job['url']}")
        
    print("\n==============================")
    print("ALREADY VISITED")
    print("==============================")
    # Group by repository to preserve order
    for job in already_visited_list:
        print(f"\nCompany: {job['company']}")
        print(f"Title: {job['title']}")
        print(f"Repository: {job['repository']}")
        
    # Print Summary
    print("\n==============================")
    print("SUMMARY")
    print("==============================")
    print(f"Total jobs scraped:       {total_scraped}")
    print(f"Duplicate jobs removed:   {total_removed}")
    print(f"Already visited:          {len(already_visited_list)}")
    print(f"Opened (in DB):           {opened_count}")
    print(f"Applied (in DB):          {applied_count}")
    print(f"Skipped (in DB):          {skipped_count}")
    print(f"New jobs:                 {len(new_jobs_list)}")
    print("==============================")
    
    # Generate/regenerate reports
    interacted_map = {}
    for job in updated_tracked.values():
        if job["status"] in ("applied", "skipped", "opened"):
            key = (job["company"].lower().strip(), job["title"].lower().strip())
            interacted_map[key] = job["status"]

    new_jobs_to_export = [
        {
            "company": j["company"],
            "title": j["title"],
            "location": j["location"],
            "repository": j["repository"],
            "category": j.get("category", "Other"),
            "salary": j.get("salary", ""),
            "age": j.get("age", ""),
            "url": j["url"],
            "similar_status": interacted_map.get((j["company"].lower().strip(), j["title"].lower().strip()), "")
        }
        for j in new_jobs_list
    ]
    generate_csv(new_jobs_to_export)
    generate_html(new_jobs_to_export)

    # Handle --open flag or --daily interactive prompts
    if args.open:
        urls_to_open = [job["url"] for job in new_jobs_list]
        open_urls_in_chrome(urls_to_open)
        # Bulk update their status to opened
        norm_urls = [job["normalized_url"] for job in new_jobs_list]
        # Insert them if they weren't stored (e.g. if we are on first run and didn't insert new jobs)
        # Make sure they are in DB
        for job in new_jobs_list:
            job["status"] = "opened"
            job["date_opened"] = datetime.now().isoformat()
        insert_jobs(new_jobs_list) # insert or replace/ignore
        update_jobs_status_bulk(norm_urls, "opened", mark_opened=True)
        print(f"Marked {len(new_jobs_list)} jobs as 'opened' in applied.db.")
        
    elif args.daily:
        print("\nOpen all NEW jobs in Chrome? (Y/N)")
        try:
            choice = input("> ").strip().lower()
            if choice in ("y", "yes"):
                urls_to_open = [job["url"] for job in new_jobs_list]
                open_urls_in_chrome(urls_to_open)
                norm_urls = [job["normalized_url"] for job in new_jobs_list]
                # Ensure they are saved in database with status 'opened'
                for job in new_jobs_list:
                    job["status"] = "opened"
                    job["date_opened"] = datetime.now().isoformat()
                insert_jobs(new_jobs_list)
                update_jobs_status_bulk(norm_urls, "opened", mark_opened=True)
                print(f"Marked {len(new_jobs_list)} jobs as 'opened' in applied.db.")
            else:
                print("Leave statuses unchanged. No jobs opened.")
        except (KeyboardInterrupt, EOFError):
            print("\nAction cancelled.")

if __name__ == "__main__":
    main()
