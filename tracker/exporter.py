import json
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from tracker.config import BASE_DIR, setup_logging

logger = setup_logging()

def generate_csv(new_jobs: List[Dict[str, Any]], output_path: Path = BASE_DIR / "new_jobs.csv") -> None:
    """Generates a CSV file containing all new jobs."""
    if not new_jobs:
        # Create empty CSV with columns
        df = pd.DataFrame(columns=["company", "title", "location", "repository", "category", "salary", "age", "url"])
    else:
        df = pd.DataFrame(new_jobs)
        # Select and reorder columns
        df = df[["company", "title", "location", "repository", "category", "salary", "age", "url"]]
        
    df.to_csv(output_path, index=False, encoding="utf-8")
    logger.info(f"Generated CSV with {len(new_jobs)} jobs at: {output_path}")

def generate_html(new_jobs: List[Dict[str, Any]], output_path: Path = BASE_DIR / "new_jobs.html") -> None:
    """Generates a modern, responsive HTML page to browse new jobs."""
    jobs_json = json.dumps(new_jobs)
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JobTracker - New Graduate Opportunities</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.6);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #10b981;
            --danger: #ef4444;
            --shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.05) 0px, transparent 50%);
            color: var(--text-primary);
            font-family: 'Plus Jakarta Sans', sans-serif;
            min-height: 100vh;
            padding: 2rem 1rem;
            line-height: 1.5;
            scroll-behavior: smooth;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 2rem;
        }}

        h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #60a5fa 0%, #34d399 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .stats-badge {{
            display: inline-block;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: #93c5fd;
            padding: 0.25rem 1rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }}

        /* Undo panel styling */
        .undo-container {{
            display: flex;
            justify-content: center;
            margin-bottom: 1.5rem;
        }}

        .undo-btn {{
            background: rgba(52, 211, 153, 0.15);
            border: 1px solid rgba(52, 211, 153, 0.3);
            color: #34d399;
            padding: 0.5rem 1.2rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.85rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            transition: all 0.2s ease;
            backdrop-filter: blur(8px);
            font-family: inherit;
        }}

        .undo-btn:hover {{
            background: rgba(52, 211, 153, 0.3);
            transform: translateY(-1px);
        }}

        .undo-btn:disabled {{
            opacity: 0.3;
            cursor: not-allowed;
            background: transparent;
            border-color: var(--card-border);
            color: var(--text-secondary);
            transform: none;
        }}

        /* Tabs styling */
        .tabs-container {{
            display: flex;
            justify-content: center;
            gap: 0.75rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }}

        .tab-btn {{
            padding: 0.6rem 1.2rem;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 9999px;
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.9rem;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.3s ease;
            backdrop-filter: blur(12px);
        }}

        .tab-btn:hover {{
            border-color: rgba(59, 130, 246, 0.4);
            color: var(--text-primary);
        }}

        .tab-btn.active {{
            background: var(--accent);
            border-color: var(--accent);
            color: white;
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.4);
        }}

        /* Search and Filter Panel */
        .controls-panel {{
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.25rem;
            margin-bottom: 2rem;
            box-shadow: var(--shadow);
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            align-items: center;
        }}

        .search-box {{
            flex: 1;
            min-width: 280px;
        }}

        .search-box input {{
            width: 100%;
            padding: 0.75rem 1rem;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 1rem;
            transition: all 0.3s ease;
        }}

        .search-box input:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
        }}

        .filter-group {{
            display: flex;
            gap: 1rem;
            align-items: center;
            flex-wrap: wrap;
        }}

        .sort-select {{
            padding: 0.75rem 1rem;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.95rem;
            cursor: pointer;
            outline: none;
            transition: all 0.3s ease;
        }}

        .sort-select:focus {{
            border-color: var(--accent);
        }}

        /* Section navigation bar */
        .section-nav-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.75rem;
            margin-bottom: 2rem;
            background: rgba(22, 28, 45, 0.4);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 0.6rem 1rem;
            flex-wrap: wrap;
            box-shadow: var(--shadow);
            backdrop-filter: blur(8px);
        }}

        .section-nav-label {{
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .section-nav-btn {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            padding: 0.35rem 0.75rem;
            color: #93c5fd;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            font-family: inherit;
        }}

        .section-nav-btn:hover {{
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }}

        /* Grouped Sections styling */
        .repo-group {{
            background: rgba(15, 23, 42, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 20px;
            padding: 1.75rem;
            margin-bottom: 2.5rem;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.2);
            scroll-margin-top: 1.5rem;
        }}

        .repo-title {{
            font-size: 1.6rem;
            font-weight: 700;
            color: #93c5fd;
            margin-bottom: 1.5rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 0.5rem;
            letter-spacing: -0.02em;
        }}

        .category-group {{
            margin-bottom: 2rem;
            scroll-margin-top: 2rem;
        }}

        .category-group:last-child {{
            margin-bottom: 0;
        }}

        .category-title {{
            font-size: 1.15rem;
            font-weight: 600;
            color: #34d399;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        /* Jobs Grid */
        .jobs-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 1.25rem;
        }}

        /* Card styling */
        .job-card {{
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: var(--shadow);
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.3s ease;
            position: relative;
        }}

        .job-card:hover {{
            transform: translateY(-4px);
            border-color: rgba(59, 130, 246, 0.4);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.5rem;
            margin-bottom: 0.4rem;
        }}

        .company-name {{
            font-size: 0.85rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--success);
        }}

        .close-btn {{
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 1.25rem;
            cursor: pointer;
            padding: 0;
            line-height: 1;
            transition: color 0.2s, transform 0.1s;
            opacity: 0.4;
            margin-top: -2px;
        }}

        .close-btn:hover {{
            color: var(--danger);
            opacity: 1;
            transform: scale(1.15);
        }}

        .job-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.75rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            min-height: 3.3rem;
        }}

        .job-meta {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 1.25rem;
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .meta-icon {{
            width: 14px;
            height: 14px;
            fill: currentColor;
            opacity: 0.7;
        }}

        .salary-badge {{
            display: inline-flex;
            align-items: center;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.25);
            color: #34d399;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
            align-self: flex-start;
        }}

        .badge-group {{
            display: flex;
            gap: 0.5rem;
            margin-top: 0.25rem;
            flex-wrap: wrap;
        }}

        .age-badge {{
            display: inline-flex;
            align-items: center;
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.25);
            color: #93c5fd;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
            align-self: flex-start;
        }}

        .warning-badge {{
            display: inline-flex;
            align-items: center;
            background: rgba(245, 158, 11, 0.12);
            border: 1px solid rgba(245, 158, 11, 0.25);
            color: #fbbf24;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
            align-self: flex-start;
        }}

        .apply-btn {{
            display: block;
            text-align: center;
            background: var(--accent);
            color: white;
            padding: 0.7rem;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 600;
            font-size: 0.9rem;
            transition: background-color 0.2s, transform 0.1s;
        }}

        .apply-btn:hover {{
            background: var(--accent-hover);
        }}

        .apply-btn:active {{
            transform: scale(0.98);
        }}

        .no-results {{
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
            font-size: 1.2rem;
            width: 100%;
        }}

        @media (max-width: 768px) {{
            .controls-panel {{
                flex-direction: column;
                align-items: stretch;
            }}
            .search-box {{
                width: 100%;
            }}
            .filter-group {{
                width: 100%;
                justify-content: space-between;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>JobTracker Dashboard</h1>
            <div id="stats-container">
                <span class="stats-badge" id="stats-badge">Loading...</span>
            </div>
        </header>

        <div class="tabs-container">
            <button class="tab-btn active" data-repo="all" onclick="setTab('all')">All Repositories</button>
            <button class="tab-btn" data-repo="2027-AI-College-Jobs" onclick="setTab('2027-AI-College-Jobs')">2027 AI College Jobs</button>
            <button class="tab-btn" data-repo="SimplifyJobs" onclick="setTab('SimplifyJobs')">SimplifyJobs</button>
            <button class="tab-btn" data-repo="2027-SWE-College-Jobs" onclick="setTab('2027-SWE-College-Jobs')">2027 SWE College Jobs</button>
        </div>

        <div class="undo-container">
            <button class="undo-btn" id="undo-btn" onclick="undoLastAction()" disabled>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 7v6h6M21 17a9 9 0 00-9-9 9 9 0 00-6 2.3L3 13"/></svg>
                Undo Last Action
            </button>
        </div>

        <div class="controls-panel">
            <div class="search-box">
                <input type="text" id="search-input" placeholder="Search by company, title, or location...">
            </div>
            <div class="filter-group">
                <select id="sort-select" class="sort-select">
                    <option value="none">Latest to Oldest (Default)</option>
                    <option value="salary-desc">Sort by Salary (High to Low)</option>
                    <option value="salary-asc">Sort by Salary (Low to High)</option>
                    <option value="salary-undefined">Undefined Salary</option>
                    <option value="company">Sort by Company</option>
                    <option value="location">Sort by Location</option>
                </select>
            </div>
        </div>

        <div id="section-nav-bar" class="section-nav-container" style="display: none;">
            <span class="section-nav-label">Toggle Sections:</span>
            <div id="section-nav-links" style="display: flex; gap: 0.5rem; flex-wrap: wrap;"></div>
        </div>

        <div id="dashboard-content">
            <!-- Structured groups will be dynamically rendered here -->
        </div>
    </div>

    <script>
        const jobs = {jobs_json};
        let activeTab = 'all';
        const undoStack = [];
        const disabledSections = new Set();

        const searchInput = document.getElementById('search-input');
        const sortSelect = document.getElementById('sort-select');
        const statsBadge = document.getElementById('stats-badge');
        const dashboardContent = document.getElementById('dashboard-content');
        const navBar = document.getElementById('section-nav-bar');
        const navLinks = document.getElementById('section-nav-links');
        const undoBtn = document.getElementById('undo-btn');

        // Retrieve local storage rules
        function getLocalStorageSet(key) {{
            return new Set(JSON.parse(localStorage.getItem(key) || '[]'));
        }}

        function saveLocalStorageSet(key, set) {{
            localStorage.setItem(key, JSON.stringify(Array.from(set)));
        }}

        function setTab(tabName) {{
            activeTab = tabName;
            document.querySelectorAll('.tab-btn').forEach(btn => {{
                if (btn.getAttribute('data-repo') === tabName) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});
            filterAndSortJobs();
        }}

        function hideJob(url, actionType = 'hide') {{
            const key = actionType === 'apply' ? 'applied_locally' : 'hidden_urls';
            const s = getLocalStorageSet(key);
            s.add(url);
            saveLocalStorageSet(key, s);
            
            undoStack.push({{ action: actionType, url: url }});
            updateUndoState();
            filterAndSortJobs();
        }}

        function undoLastAction() {{
            if (undoStack.length === 0) return;
            const last = undoStack.pop();
            const key = last.action === 'apply' ? 'applied_locally' : 'hidden_urls';
            
            const s = getLocalStorageSet(key);
            s.delete(last.url);
            saveLocalStorageSet(key, s);
            
            updateUndoState();
            filterAndSortJobs();
        }}

        function updateUndoState() {{
            undoBtn.disabled = (undoStack.length === 0);
        }}

        function renderDashboard(filteredJobs) {{
            dashboardContent.innerHTML = '';
            navLinks.innerHTML = '';
            const navButtons = [];
            
            // Get hidden collections
            const hiddenSet = getLocalStorageSet('hidden_urls');
            const appliedSet = getLocalStorageSet('applied_locally');

            // Filter out hidden/locally applied cards
            const visibleJobs = filteredJobs.filter(job => !hiddenSet.has(job.url) && !appliedSet.has(job.url));

            // Filter by active tab
            let tabFiltered = visibleJobs;
            if (activeTab !== 'all') {{
                tabFiltered = visibleJobs.filter(job => {{
                    if (activeTab === 'SimplifyJobs') {{
                        return job.repository.startsWith('SimplifyJobs');
                    }}
                    return job.repository === activeTab;
                }});
            }}

            if (tabFiltered.length === 0) {{
                dashboardContent.innerHTML = '<div class="no-results">No new jobs found matching your filters.</div>';
                statsBadge.textContent = '0 New Jobs';
                navBar.style.display = 'none';
                return;
            }}

            statsBadge.textContent = `${{tabFiltered.length}} New Jobs Available`;

            // Structured groupings mimicking target repositories
            const groups = {{
                "2027-AI-College-Jobs": {{
                    title: "2027 AI College Jobs",
                    categories: {{ "FAANG": [], "Finance": [], "Other": [] }}
                }},
                "SimplifyJobs": {{
                    title: "SimplifyJobs",
                    categories: {{ 
                        "Software Engineering": [], 
                        "Data Science, AI & Machine Learning": [] 
                    }}
                }},
                "2027-SWE-College-Jobs": {{
                    title: "2027 SWE College Jobs",
                    categories: {{ "FAANG": [], "Finance": [], "Other": [] }}
                }}
            }};

            // Distribute jobs into groups
            tabFiltered.forEach(job => {{
                if (job.repository === "2027-AI-College-Jobs") {{
                    const cat = job.category || "Other";
                    if (groups["2027-AI-College-Jobs"].categories[cat]) {{
                        groups["2027-AI-College-Jobs"].categories[cat].push(job);
                    }} else {{
                        groups["2027-AI-College-Jobs"].categories["Other"].push(job);
                    }}
                }} else if (job.repository.startsWith("SimplifyJobs")) {{
                    const cat = (job.category === "Data Science, AI & Machine Learning" || job.category === "Data Science/AI/ML") 
                        ? "Data Science, AI & Machine Learning" 
                        : "Software Engineering";
                    groups["SimplifyJobs"].categories[cat].push(job);
                }} else if (job.repository === "2027-SWE-College-Jobs") {{
                    const cat = job.category || "Other";
                    if (groups["2027-SWE-College-Jobs"].categories[cat]) {{
                        groups["2027-SWE-College-Jobs"].categories[cat].push(job);
                    }} else {{
                        groups["2027-SWE-College-Jobs"].categories["Other"].push(job);
                    }}
                }}
            }});

            // Render groups
            Object.keys(groups).forEach(groupKey => {{
                const group = groups[groupKey];
                
                // Count how many jobs in this group
                let groupJobCount = 0;
                Object.keys(group.categories).forEach(catKey => {{
                    groupJobCount += group.categories[catKey].length;
                }});

                if (groupJobCount === 0) return;

                const groupDiv = document.createElement('div');
                groupDiv.className = 'repo-group';
                
                const groupTitle = document.createElement('h2');
                groupTitle.className = 'repo-title';
                groupTitle.textContent = group.title;
                groupDiv.appendChild(groupTitle);

                // Render categories inside group
                Object.keys(group.categories).forEach(catKey => {{
                    const catJobs = group.categories[catKey];
                    if (catJobs.length === 0) return;

                    const sectionId = 'sec-' + groupKey + '-' + catKey.replace(/\s+/g, '-').replace(/[^a-zA-Z0-9-]/g, '').toLowerCase();

                    const catDiv = document.createElement('div');
                    catDiv.className = 'category-group';
                    catDiv.id = sectionId;
                    if (disabledSections.has(sectionId)) {{
                        catDiv.style.display = 'none';
                    }}
                    
                    const catTitle = document.createElement('h3');
                    catTitle.className = 'category-title';
                    
                    // Add emojis or clean display names
                    let dispName = catKey;
                    let dispNameShort = catKey;
                    if (catKey === "FAANG") {{
                        dispName = "🔥 FAANG+ Roles";
                        dispNameShort = "FAANG+";
                    }} else if (catKey === "Finance") {{
                        dispName = "📈 Finance & Quant Roles";
                        dispNameShort = "Finance/Quant";
                    }} else if (catKey === "Other") {{
                        dispName = "💼 Other Roles";
                        dispNameShort = "Other";
                    }} else if (catKey === "Software Engineering") {{
                        dispName = "💻 Software Engineering Roles";
                        dispNameShort = "SWE";
                    }} else if (catKey === "Data Science, AI & Machine Learning") {{
                        dispName = "🤖 Data Science, AI & Machine Learning Roles";
                        dispNameShort = "DS/AI/ML";
                    }}
                    
                    catTitle.textContent = dispName;
                    catDiv.appendChild(catTitle);

                    // Add to nav buttons list
                    let buttonLabel = dispNameShort;
                    if (activeTab === 'all') {{
                        const prefix = groupKey === "2027-AI-College-Jobs" ? "AI" : (groupKey === "2027-SWE-College-Jobs" ? "SWE" : "Simplify");
                        buttonLabel = prefix + " - " + dispNameShort;
                    }}
                    navButtons.push({{
                        label: buttonLabel,
                        id: sectionId
                    }});

                    const grid = document.createElement('div');
                    grid.className = 'jobs-grid';

                    catJobs.forEach(job => {{
                        const card = document.createElement('div');
                        card.className = 'job-card';
                        
                        const salaryBadge = job.salary ? `<span class="salary-badge">💵 ${{escapeHtml(job.salary)}}</span>` : '';
                        const ageBadge = job.age ? `<span class="age-badge">📅 ${{escapeHtml(job.age)}}</span>` : '';
                        
                        let warningBadge = '';
                        if (job.similar_status) {{
                            const label = job.similar_status === 'applied' ? 'Applied' : (job.similar_status === 'skipped' ? 'Skipped' : 'Opened');
                            warningBadge = `<span class="warning-badge" title="You previously marked a similar role at this company as ${{label}}">⚠️ Similar ${{label}}</span>`;
                        }}
                        
                        card.innerHTML = `
                            <div>
                                <div class="card-header">
                                    <div class="company-name">${{escapeHtml(job.company)}}</div>
                                    <button class="close-btn" title="Dismiss Job Listing" onclick="hideJob('${{job.url}}', 'hide')">×</button>
                                </div>
                                <div class="job-title" title="${{escapeHtml(job.title)}}">${{escapeHtml(job.title)}}</div>
                                <div class="job-meta">
                                    <div class="meta-item">
                                        <svg class="meta-icon" viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                                        <span>${{escapeHtml(job.location)}}</span>
                                    </div>
                                    <div class="badge-group">
                                        ${{salaryBadge}}
                                        ${{ageBadge}}
                                        ${{warningBadge}}
                                    </div>
                                </div>
                            </div>
                            <a href="${{job.url}}" target="_blank" rel="noopener noreferrer" class="apply-btn" onclick="hideJob('${{job.url}}', 'apply')" onauxclick="if(event.button === 1) hideJob('${{job.url}}', 'apply')">Apply Now</a>
                        `;
                        grid.appendChild(card);
                    }});

                    catDiv.appendChild(grid);
                    groupDiv.appendChild(catDiv);
                }});

                dashboardContent.appendChild(groupDiv);
            }});

            // Build Section Jump Navigation Buttons
            if (navButtons.length > 1) {{
                navBar.style.display = 'flex';
                navButtons.forEach(btn => {{
                    const button = document.createElement('button');
                    button.className = 'section-nav-btn';
                    button.textContent = btn.label;
                    
                    if (disabledSections.has(btn.id)) {{
                        button.style.background = 'rgba(239, 68, 68, 0.15)';
                        button.style.borderColor = 'rgba(239, 68, 68, 0.3)';
                        button.style.color = '#f87171';
                        button.style.textDecoration = 'line-through';
                    }}
                    
                    button.onclick = () => {{
                        toggleSection(btn.id);
                    }};
                    navLinks.appendChild(button);
                }});
            }} else {{
                navBar.style.display = 'none';
            }}
        }}

        function escapeHtml(str) {{
            if (!str) return '';
            return str.replace(/&/g, "&amp;")
                      .replace(/</g, "&lt;")
                      .replace(/>/g, "&gt;")
                      .replace(/"/g, "&quot;")
                      .replace(/'/g, "&#039;");
        }}

        function parseSalaryValue(salaryStr) {{
            if (!salaryStr) return 0;
            let cleaned = salaryStr.toLowerCase().replace(/,/g, '');
            // Convert abbreviations (e.g. 100k -> 100000)
            cleaned = cleaned.replace(/([0-9.]+)\s*k/g, (match, num) => parseFloat(num) * 1000);
            
            let numbers = cleaned.match(/[0-9]+(?:\.[0-9]+)?/g);
            if (!numbers || numbers.length === 0) return 0;
            
            let values = numbers.map(n => parseFloat(n));
            
            // Check if hourly and estimate yearly
            let isHourly = cleaned.includes('hr') || cleaned.includes('hour') || values.some(v => v < 200);
            if (isHourly) {{
                values = values.map(v => v * 2000); // 2000 hours/yr
            }}
            
            return Math.max(...values);
        }}

        function filterAndSortJobs() {{
            const query = searchInput.value.toLowerCase().trim ? searchInput.value.toLowerCase().trim() : searchInput.value.toLowerCase();
            const sortBy = sortSelect.value;

            // 1. Filter by search query
            let filtered = jobs.filter(job => {{
                return (
                    job.company.toLowerCase().includes(query) ||
                    job.title.toLowerCase().includes(query) ||
                    job.location.toLowerCase().includes(query)
                );
            }});

            // 2. Separate/filter undefined salaries from sorted lists
            if (sortBy === 'salary-desc' || sortBy === 'salary-asc') {{
                filtered = filtered.filter(job => job.salary && job.salary.trim() !== "");
            }} else if (sortBy === 'salary-undefined') {{
                filtered = filtered.filter(job => !job.salary || job.salary.trim() === "");
            }}

            // 3. Sort
            if (sortBy === 'company') {{
                filtered.sort((a, b) => a.company.localeCompare(b.company));
            }} else if (sortBy === 'location') {{
                filtered.sort((a, b) => a.location.localeCompare(b.location));
            }} else if (sortBy === 'salary-desc') {{
                filtered.sort((a, b) => parseSalaryValue(b.salary) - parseSalaryValue(a.salary));
            }} else if (sortBy === 'salary-asc') {{
                filtered.sort((a, b) => parseSalaryValue(a.salary) - parseSalaryValue(b.salary));
            }}

            renderDashboard(filtered);
        }}

        function toggleSection(sectionId) {{
            if (disabledSections.has(sectionId)) {{
                disabledSections.delete(sectionId);
            }} else {{
                disabledSections.add(sectionId);
            }}
            filterAndSortJobs();
        }}

        searchInput.addEventListener('input', filterAndSortJobs);
        sortSelect.addEventListener('change', filterAndSortJobs);

        // Initial render
        renderDashboard(jobs);
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    logger.info(f"Generated HTML Dashboard with {len(new_jobs)} jobs at: {output_path}")
