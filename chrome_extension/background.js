// Lines up open job tabs by resume fit: best match right after the dashboard
// tab, weakest farthest right. chrome.tabs.move keeps each tab as it is
// (scroll position, half-filled forms), unlike reopening it.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'arrange-tabs' || !sender.tab) return;
  arrangeTabs(sender.tab).then(sendResponse, (e) => sendResponse({ error: String(e) }));
  return true; // respond asynchronously
});

async function arrangeTabs(dashboard) {
  const tabs = (await chrome.tabs.query({})).filter((t) => t.id !== dashboard.id && t.url);
  const origin = new URL(dashboard.url).origin;
  const resp = await fetch(`${origin}/api/tab_scores`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls: tabs.map((t) => t.url) }),
  });
  const { scores } = await resp.json();

  // Pinned tabs and tabs in other kinds of windows (popups, apps) stay put
  const windows = new Map((await chrome.windows.getAll()).map((w) => [w.id, w.type]));
  const jobTabs = tabs
    .filter((t) => scores[t.url] !== undefined && !t.pinned && windows.get(t.windowId) === 'normal')
    .sort((a, b) => scores[b.url] - scores[a.url]);
  if (!jobTabs.length) return { moved: 0 };

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
