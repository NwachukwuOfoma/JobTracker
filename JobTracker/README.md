# JobTracker 🚀

JobTracker is a production-quality Python 3.11+ CLI application designed to automate, track, and optimize the search for graduate-level roles. It scrapes job posts across three major GitHub repositories, deduplicates them, normalizes URLs (removing tracking parameters), cross-references them with both your local SQLite database (`applied.db`) and Google Chrome's local history database, and generates an interactive, high-fidelity web dashboard and a CSV file of all new jobs.

---

## Features

- **Automated Chrome History Correlation**: Scans macOS Chrome profile history database automatically, ensuring you never double-apply. It reads from a temporary copy of the history database to prevent database locking while Chrome is running.
- **Smart Deduplication**: Standardizes job URLs (strips `utm_*`, `gh_src`, `ref`, `source`, etc.) and eliminates duplicate listings across repos.
- **SQLite Tracker (`applied.db`)**: Stores normalized URLs, companies, titles, locations, and application status: `new`, `opened`, `applied`, and `skipped`.
- **Interactive UI Dashboard (`new_jobs.html`)**: Beautiful, high-performance, dark-themed responsive dashboard. Includes instant search filtering, stats, and sorting by Company, Location, or Repository.
- **Interactive CLI status management**: Easily transition jobs from `opened` to `applied` or `skipped`.

---

## Project Structure

```
JobTracker/
├── applied.db          # SQLite Database tracking application status
├── cache/              # Cached markdown files downloaded from repos
├── jobs.py             # Main entry point (Orchestrator & CLI commands)
├── logs/               # Timestamped execution log files
├── new_jobs.csv        # Output CSV containing all newly scraped positions
├── new_jobs.html       # Interactive Dashboard page
├── requirements.txt    # Python library requirements
└── tracker/            # Core logical modules
    ├── __init__.py
    ├── chrome.py       # Reads Chrome history and extracts visited URLs
    ├── config.py       # Project constants, paths, and logging setups
    ├── database.py     # SQLite schema definitions & updates
    ├── exporter.py     # CSV and HTML dashboard output generation
    ├── normalizer.py   # URL normalization & job deduplication logic
    └── scraper.py      # Repository downloaders and table parsers
```

---

## Installation

### Prerequisites
- macOS Operating System (uses macOS Chrome paths and the `open` command)
- Python 3.11+

### Step-by-Step Setup
1. Clone or copy this repository into your local system.
2. Open a terminal and navigate to the `JobTracker` workspace folder:
   ```bash
   cd "JobTracker"
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Commands & Usage

### 1. Default Check
Shows a raw summary of new and already visited jobs in the console, updates the local database, and regenerates output reports.
```bash
python jobs.py
```

### 2. Daily Workflow
Runs the scraping, deduplication, and comparison workflow. Once complete, it prompts you to open all new jobs in Chrome.
```bash
python jobs.py --daily
```
*If you type `Y` / `yes`, all newly found jobs will open in Chrome tabs and their statuses will transition to `opened` in the database.*

### 3. Open All New Jobs
Directly open all currently listed `new` jobs in Chrome without running the daily scrape again.
```bash
python jobs.py --open
```

### 4. Status Tracking
Once you visit a job, it's marked as `opened`. You can move them to `applied` or `skipped` dynamically:
- **Mark as Applied**:
  ```bash
  python jobs.py --mark-applied
  ```
- **Mark as Skipped**:
  ```bash
  python jobs.py --mark-skipped
  ```
*These commands list all currently `opened` jobs. You can input individual numbers (e.g. `2`), ranges (e.g. `1-4`), comma-separated indexes (e.g. `1, 3, 5-7`), or `all` to batch update them.*

### 5. Regenerate Exports
Instantly regenerates `new_jobs.html` and `new_jobs.csv` based on current database state.
```bash
python jobs.py --export
```

---

## URL Normalization Logic

JobTracker normalizes URLs before tracking to ensure accuracy:
- Converts schemes to `https` and domains to lowercase.
- Trims trailing slashes.
- Strips analytics/attribution parameters including `utm_*`, `gh_src`, `gh_jid`, `gh_src_id`, `ref`, and `source`.
- Removes fragments (`#`).

If two repositories list the same position with different tracking queries, they will resolve to the same normalized URL, preventing duplicate entries.
