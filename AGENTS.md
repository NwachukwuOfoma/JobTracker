# JobTracker: rules for coding agents

Fetches new-grad job postings (GitHub lists, LinkedIn guest search, company job boards),
dedupes them in SQLite, scores fit and salary with Claude, and serves a dashboard.

## Map
- `jobs.py`: the fetch pipeline (`run_fetch_pipeline`) and CLI (`--export`, `--source github|linkedin|boards`)
- `server.py`: dashboard at http://localhost:5050, run by launchd
- `tracker/database.py`: SQLite (`applied.db`); jobs are keyed by `normalized_url`
- `tracker/normalizer.py`: URL canonicalization. Every dedupe depends on it
- `tracker/job_details.py`: reads a posting's description per ATS (Workday, Greenhouse, Lever, Ashby, iCIMS, Oracle...)
- `tracker/fit_scorer.py`, `tracker/salary_estimator.py`: Claude API calls
- `tracker/exporter.py`: builds `new_jobs.html` (the dashboard UI lives here, not in server.py)
- `chrome_extension/`: opens jobs as tabs and arranges them by fit

## Hard rules
- Never use a logged-in LinkedIn session or read Chrome cookies. LinkedIn is guest endpoints only.
- Workable rate-limits for ~24h: one request per job, no retries, no listing API.
- Fetches must stay fast. Measure time before and after any change to the fetch path.
- Never drop stored jobs on refresh. A refresh only adds new ones and updates existing ones.
- Never commit `applied.db`, `logs/`, `cache/`, `.kilo/`, `new_jobs.csv` or `new_jobs.html`. The repo is public.
- A UI request means the dashboard (`tracker/exporter.py`), not a CLI flag.

## Workflow
1. Reproduce first: run the failing case and show its output before editing anything.
2. Find the root cause across all affected jobs, not just the example given.
3. Verify by running the real code path (e.g. `python3 -c "from tracker.job_details import fetch_description; ..."`, then `python3 jobs.py --export`) and show the output.
4. After changing Python code, restart the server: `launchctl kickstart -k gui/$(id -u)/com.jobtracker.server`
5. Search before reading: use `grep -n` and read only the needed line ranges of big files (`exporter.py` is ~1400 lines).
