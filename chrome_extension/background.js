// Lines up open job tabs by resume fit: best match right after the dashboard
// tab, weakest farthest right. chrome.tabs.move keeps each tab as it is
// (scroll position, half-filled forms), unlike reopening it.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender.tab) return;
  let work;
  if (message?.type === 'arrange-tabs') work = arrangeTabs(sender.tab);
  else if (message?.type === 'open-jobs') work = openJobs(sender.tab, message.jobs || []);
  else return;
  work.then(sendResponse, (e) => sendResponse({ error: String(e) }));
  return true; // respond asynchronously
});

const tabUrl = (t) => t.pendingUrl || t.url;

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

// Opens the dashboard's remaining jobs in background tabs (skipping any job
// already open under any of its links), then slots everything in by fit.
async function openJobs(dashboard, jobs) {
  const tabs = await chrome.tabs.query({});
  const jobKeys = jobs.flatMap((j) => j.keys);
  const { normalized } = await api(dashboard, '/api/normalize', { urls: [...tabs.map(tabUrl).filter(Boolean), ...jobKeys] });
  const open = new Set(tabs.map((t) => normalized[tabUrl(t)]));

  const toOpen = jobs.filter((j) => !j.keys.some((k) => open.has(normalized[k])));
  for (const job of toOpen) {
    await chrome.tabs.create({ windowId: dashboard.windowId, url: job.url, active: false });
  }
  const { moved } = await arrangeTabs(dashboard);
  return { opened: toOpen.length, alreadyOpen: jobs.length - toOpen.length, moved };
}
