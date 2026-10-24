// Runs on the JobTracker dashboard only. Passes the dashboard's tab requests
// ("Arrange Job Tabs", "Open Jobs in Tabs") to the extension and hands back the result.
const REQUESTS = {
  'jobtracker-arrange-tabs': 'arrange-tabs',
  'jobtracker-open-jobs': 'open-jobs',
};
window.addEventListener('message', (event) => {
  const type = REQUESTS[event.data?.type];
  if (event.source !== window || !type) return;
  chrome.runtime.sendMessage({ type, jobs: event.data.jobs }, (result) => {
    window.postMessage({ type: `${event.data.type}-done`, result: result || { error: 'No response from the extension' } }, '*');
  });
});
// Lets the page know the extension is installed, and which version
document.documentElement.dataset.jobtrackerExtension = '1.2';
