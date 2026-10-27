// Runs on the JobTracker dashboard only. Passes the dashboard's "Open & Arrange
// Job Tabs" and job-tab count requests to the extension and hands back the result.
const REQUESTS = {
  'jobtracker-open-and-arrange': 'open-and-arrange',
  'jobtracker-tab-count': 'tab-count',
};
window.addEventListener('message', (event) => {
  const type = REQUESTS[event.data?.type];
  if (event.source !== window || !type) return;
  chrome.runtime.sendMessage({ type, jobs: event.data.jobs }, (result) => {
    window.postMessage({ type: `${event.data.type}-done`, result: result || { error: 'No response from the extension' } }, '*');
  });
});
// The extension pushes a fresh job-tab count whenever tabs open, close or change
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === 'tab-count-update') {
    window.postMessage({ type: 'jobtracker-tab-count-done', result: message.result }, '*');
  }
});
// Lets the page know the extension is installed, and which version
document.documentElement.dataset.jobtrackerExtension = '1.8';
