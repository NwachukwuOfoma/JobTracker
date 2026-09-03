# JobTracker 🚀
### Automated New-Graduate Job Ingestion, Chrome History Correlation & Web Dashboard

**Author:** Nwachukwu Ofoma  
**Primary Stack:** Python 3.11+, SQLite, Requests, BeautifulSoup4, Pandas, HTML5/CSS3/JavaScript  
**Type:** Production-Grade CLI Application & Data Pipeline  

---

## 1. Project Overview & Problem Statement

Applying to competitive early-career and new-graduate software engineering / AI roles requires monitoring dozens of fast-moving aggregator feeds (such as community-maintained GitHub repositories) without double-applying or missing rolling deadlines. 

However, standard manual tracking presents several key engineering hurdles:
1. **Repository Redundancy:** The same positions are cross-posted across multiple repositories with varying URL structures and tracking tokens (`utm_*`, `gh_src`, `ref`, etc.).
2. **Double-Application Risk:** Manually checking whether an applicant has already visited or applied to a role across dozens of tabs is prone to human error.
3. **Database Concurrency Locks:** Reading active browser history directly from Google Chrome's SQLite database often crashes or fails due to OS-level file locks while the browser is running.
4. **Missing Compensation Data:** Most community markdown tables lack transparent salary numbers, requiring external request crawling across diverse applicant tracking systems (ATS).

**JobTracker** solves these challenges end-to-end. It continuously scrapes, deduplicates, and normalizes job opportunities from top GitHub repositories, cross-references them in real time against both a local SQLite database and Google Chrome's local history database (using zero-lock temporary clones), extracts compensation via ATS APIs, and generates both an interactive dark-themed web dashboard and a prioritized CSV.

---

## 2. System Architecture & Data Pipeline

```
+-------------------------------------------------------------------------+
|                          JOBTRACKER DATA FLOW                           |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
         [ Multi-Source Scraper (GitHub Markdown & HTML Tables) ]
         - speedyapply/2027-AI-College-Jobs
         - SimplifyJobs/New-Grad-Positions
         - speedyapply/2027-SWE-College-Jobs
                                     │
                                     ▼
                     [ URL Normalization Engine ]
                     - Strip analytics & attribution parameters
                     - Canonicalize ATS domains (Greenhouse, Workday, ByteDance)
                     - Cross-repository deduplication
                                     │
                                     ▼
               [ Zero-Lock Chrome History Correlator ]
               - Clones macOS Chrome SQLite DB to temp partition
               - Opens via URI read-only mode (`?mode=ro`)
               - Identifies previously visited positions
                                     │
                                     ▼
               [ Concurrent Compensation Discovery Engine ]
               - Reverse engineers Workday, Workable, Greenhouse & Eightfold APIs
               - Schema.org JSON-LD parsing & heuristic regex fallback
               - Automatic detection & skipping of expired/dead links
                                     │
                                     ▼
                    [ SQLite State Machine (applied.db) ]
                    - State lifecycle: new -> opened -> applied / skipped
                    - Date tracking (date_first_seen, date_opened)
                                     │
                                     ▼
                    [ Exporters & Web Dashboard ]
                    - new_jobs.csv: Filtered, structured dataset
                    - new_jobs.html: Responsive dark-mode dashboard with
                      instant search, section navigation, and undo stack
```

---

## 3. Key Technical Highlights

### 1. Zero-Lock Chrome History Extraction (`tracker/chrome.py`)
Directly opening an active browser's SQLite database (`~/Library/Application Support/Google/Chrome/Default/History`) typically triggers database lock errors (`sqlite3.OperationalError: database is locked`). JobTracker resolves this safely:
- Discovers all local profile directories dynamically (`Default`, `Profile 1`, etc.).
- Atomically duplicates the history file to a temporary OS partition (`tempfile.TemporaryDirectory`).
- Mounts the clone in strict read-only mode (`file:{path}?mode=ro&immutable=1`), ensuring non-blocking reads while the user continues browsing uninterrupted.

### 2. Algorithmic URL Normalization & Deduplication (`tracker/normalizer.py`)
To prevent the same role from appearing multiple times under different tracking links:
- Strips 15+ tracking and referral query parameters (`gh_src`, `gh_jid`, `ref`, `source`, `utm_*`).
- Canonicalizes subdomain variations (e.g. normalizing third-party Greenhouse endpoints to `boards.greenhouse.io`).
- Strips locale prefixes (`/en-us/`, `/fr/`) and action paths (`/apply`, `/resume`, `/detail`).
- Extracts immutable entity IDs (e.g. 19-digit ByteDance/TikTok requisition identifiers).

### 3. Concurrent Multi-Platform Compensation Scraping (`tracker/scraper.py`)
When salary data is missing from markdown feeds, JobTracker concurrently inspects the target destination (`ThreadPoolExecutor`):
- **Workday CXS REST APIs:** Automatically transforms human-facing Workday URLs into their underlying REST endpoints (`/wday/cxs/{tenant}/{rb}/job/{job_path}`) to query clean JSON payloads.
- **Workable & Greenhouse APIs:** Extracts board tokens and requisition IDs to pull structured metadata.
- **Structured JSON-LD:** Parses Schema.org `JobPosting` structured microdata directly from HTML heads before executing fallback regex searches.
- **Dead Link Filtering:** Automatically identifies closed or 404 postings (`__DEAD__`) and marks them as skipped, preventing wasted applications.

### 4. Interactive Client-Side Web Dashboard (`new_jobs.html`)
JobTracker exports a self-contained, high-performance HTML/CSS/JavaScript web dashboard:
- Glassmorphic dark UI built with pure CSS and CSS variables.
- Instant client-side fuzzy searching across Company, Title, and Location.
- Salary sort options (High-to-Low, Low-to-High, Undefined) and repository tab filters.
- Local browser state management (`localStorage`) with an active Undo stack for dismissed postings.

---

## 4. Repository & Package Structure

```
JobTracker/
├── jobs.py                 # Core CLI orchestrator, argument parser & workflow controller
├── requirements.txt        # Locked Python dependencies (requests, beautifulsoup4, pandas)
├── README.md               # Technical overview and documentation
├── new_jobs.html           # Generated interactive web dashboard
├── new_jobs.csv            # Generated tabular export
└── tracker/                # Modular internal architecture
    ├── __init__.py
    ├── chrome.py           # Zero-lock Google Chrome history reader
    ├── config.py           # Application constants, paths, and logging configuration
    ├── database.py         # SQLite schema initialization, CRUD operations & state updates
    ├── exporter.py         # Dynamic CSV and HTML web dashboard generators
    ├── normalizer.py       # URL canonicalization and job deduplication engine
    └── scraper.py          # GitHub table parsers, HTTP caching & ATS salary APIs
```

---

## 5. Getting Started & Usage

### Prerequisites
- Python 3.11+
- macOS (for native Chrome history integration and browser dispatch)

### Installation
```bash
# Clone or extract archive
cd JobTracker

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install minimal dependencies
pip install -r requirements.txt
```

### Running the Application

1. **Scrape & Audit (Default):**
   ```bash
   python jobs.py
   ```
   *Fetches the latest job repositories, strips duplicates, cross-references visited links, updates `applied.db`, and regenerates `new_jobs.html` and `new_jobs.csv`.*

2. **Daily Interactive Workflow:**
   ```bash
   python jobs.py --daily
   ```
   *Runs the pipeline and offers a 1-click prompt (`Y/N`) to open all new jobs in Chrome tabs, immediately transitioning their database status to `opened`.*

3. **Status Lifecycle Management:**
   ```bash
   # Interactively mark opened roles as applied
   python jobs.py --mark-applied

   # Interactively mark opened roles as skipped
   python jobs.py --mark-skipped
   ```
   *Supports flexible input expressions: single integers (`3`), comma-separated lists (`1, 4, 7`), ranges (`2-6`), or `all`.*

4. **Regenerate Exports:**
   ```bash
   python jobs.py --export
   ```

---

## 6. Design Principles

- **Defensive Engineering:** Automated cache invalidation (6-hour window) with automatic fallback to stale cache during network outages.
- **Privacy & Security:** Zero tracking tokens or credentials required; all operations execute locally against local SQLite instances.
- **Modularity:** Separation of concerns between ingestion (`scraper.py`), normalization (`normalizer.py`), persistence (`database.py`), and visualization (`exporter.py`).
