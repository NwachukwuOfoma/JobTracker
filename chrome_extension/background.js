// Lines up open job tabs by resume fit: best match right after the dashboard
// tab, weakest farthest right. chrome.tabs.move keeps each tab as it is
// (scroll position, half-filled forms), unlike reopening it.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender.tab) return;
  let work;
  if (message?.type === 'open-and-arrange') work = openJobs(sender.tab, message.jobs || []);
  else if (message?.type === 'tab-count') work = countTabs(sender.tab);
  else if (message?.type === 'draft-answers') work = draftAnswers(sender.tab, message);
  else if (message?.type === 'panel-closed') work = setPanelTab(sender.tab.id, false);
  else return;
  work.then(sendResponse, (e) => sendResponse({ error: String(e) }));
  return true; // respond asynchronously
});

const LAZY_PAGE = chrome.runtime.getURL('lazy.html');

// The job a tab holds: placeholder tabs carry it in their ?url= parameter
const tabUrl = (t) => {
  const url = t.pendingUrl || t.url;
  if (url && url.startsWith(LAZY_PAGE)) return new URL(url).searchParams.get('url');
  return url;
};

async function api(dashboard, path, body) {
  const resp = await fetch(`${new URL(dashboard.url).origin}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

async function arrangeTabs(dashboard) {
  const tabs = (await chrome.tabs.query({})).filter((t) => t.id !== dashboard.id && tabUrl(t));
  const { scores } = await api(dashboard, '/api/tab_scores', { urls: tabs.map(tabUrl) });

  // Pinned tabs and tabs in other kinds of windows (popups, apps) stay put
  const windows = new Map((await chrome.windows.getAll()).map((w) => [w.id, w.type]));
  const jobTabs = tabs
    .filter((t) => scores[tabUrl(t)] !== undefined && !t.pinned && windows.get(t.windowId) === 'normal')
    .sort((a, b) => scores[tabUrl(b)] - scores[tabUrl(a)]);

  // One at a time, re-reading the dashboard's position, since tabs moved out
  // from in front of it shift its index
  for (const [i, tab] of jobTabs.entries()) {
    const current = await chrome.tabs.get(dashboard.id);
    const now = await chrome.tabs.get(tab.id);
    // A tab coming from the dashboard's left frees a slot, so the target shifts by one
    const fromLeft = now.windowId === current.windowId && now.index < current.index;
    await chrome.tabs.move(tab.id, { windowId: current.windowId, index: current.index + i + (fromLeft ? 0 : 1) });
  }
  return { moved: jobTabs.length };
}

// Opens the dashboard's remaining jobs (skipping any job already open under any
// of its links) as placeholder tabs that load the real page when you switch to
// them, then slots every job tab in by fit. With no jobs it just arranges.
async function openJobs(dashboard, jobs) {
  const tabs = await chrome.tabs.query({});
  const jobKeys = jobs.flatMap((j) => j.keys);
  const { normalized } = await api(dashboard, '/api/normalize', { urls: [...tabs.map(tabUrl).filter(Boolean), ...jobKeys] });
  const open = new Set(tabs.map((t) => normalized[tabUrl(t)]));

  const toOpen = jobs.filter((j) => !j.keys.some((k) => open.has(normalized[k])));
  for (const job of toOpen) {
    const lazy = `${LAZY_PAGE}?${new URLSearchParams({ url: job.url, title: job.title || '', fit: job.fit ?? '' })}`;
    await chrome.tabs.create({ windowId: dashboard.windowId, url: lazy, active: false });
  }
  const { moved } = await arrangeTabs(dashboard);
  return { opened: toOpen.length, alreadyOpen: jobs.length - toOpen.length, moved };
}

// How many open tabs are jobs JobTracker knows (Chrome's tab strip stops showing
// them once there are too many), and how many of those haven't loaded yet
async function countTabs(dashboard) {
  const tabs = (await chrome.tabs.query({})).filter((t) => t.id !== dashboard.id && tabUrl(t));
  const { jobs } = await api(dashboard, '/api/tab_scores', { urls: tabs.map(tabUrl) });
  const known = new Set(jobs);
  const jobTabs = tabs.filter((t) => known.has(tabUrl(t)));
  return {
    jobTabs: jobTabs.length,
    notLoaded: jobTabs.filter((t) => (t.pendingUrl || t.url || '').startsWith(LAZY_PAGE)).length,
  };
}

// Keeps the count on every open dashboard current as tabs open, close or navigate
let countTimer;
function refreshCounts() {
  clearTimeout(countTimer);
  countTimer = setTimeout(async () => {
    const dashboards = await chrome.tabs.query({ url: ['http://localhost:5050/*', 'http://127.0.0.1:5050/*'] });
    for (const dashboard of dashboards) {
      try {
        const result = await countTabs(dashboard);
        await chrome.tabs.sendMessage(dashboard.id, { type: 'tab-count-update', result });
      } catch (e) {
        // Dashboard still loading or the server is down; the next change retries
      }
    }
  }, 500);
}
chrome.tabs.onCreated.addListener(refreshCounts);
chrome.tabs.onRemoved.addListener(refreshCounts);
chrome.tabs.onUpdated.addListener((id, change) => { if (change.url) refreshCounts(); });

// Looks for open-ended questions in every frame of the page (forms are often
// embedded), then opens the answer panel in the frame that has them
async function showPanel(tabId) {
  let results = [];
  try {
    results = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ['answer_panel.js'] });
  } catch (e) {
    return; // a page extensions can't touch, like chrome:// pages or the Web Store
  }
  const best = results.reduce((a, b) => ((b.result || 0) > (a.result || 0) ? b : a), { frameId: 0, result: 0 });
  await chrome.scripting.executeScript({
    target: { tabId, frameIds: [best.frameId] },
    func: () => window.__jobtrackerAnswers.open(),
  });
}

// Tabs with the panel open: it comes back on each new page in that tab until you close it
async function panelTabs() {
  return (await chrome.storage.session.get('panelTabs')).panelTabs || {};
}
async function setPanelTab(tabId, open) {
  const tabs = await panelTabs();
  if (open) tabs[tabId] = true;
  else delete tabs[tabId];
  await chrome.storage.session.set({ panelTabs: tabs });
}

chrome.action.onClicked.addListener(async (tab) => {
  await setPanelTab(tab.id, true);
  await showPanel(tab.id);
});
chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  if (change.status === 'complete' && (await panelTabs())[tabId]) showPanel(tabId);
});
chrome.tabs.onRemoved.addListener((tabId) => { setPanelTab(tabId, false); });

// The answer panel's drafts come from the JobTracker server (it holds the resume and API key)
async function draftAnswers(tab, message) {
  const resp = await fetch('http://localhost:5050/api/draft_answers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      urls: [tab.url, message.frameUrl],
      title: message.title,
      page_text: message.pageText,
      questions: message.questions,
    }),
  });
  return resp.json();
}
