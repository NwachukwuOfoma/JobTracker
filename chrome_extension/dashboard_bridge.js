// Runs on the JobTracker dashboard only. Passes the dashboard's
// "Arrange Job Tabs" request to the extension and hands back the result.
window.addEventListener('message', (event) => {
  if (event.source !== window || event.data?.type !== 'jobtracker-arrange-tabs') return;
  chrome.runtime.sendMessage({ type: 'arrange-tabs' }, (result) => {
    window.postMessage({ type: 'jobtracker-arrange-tabs-done', result: result || { error: 'No response from the extension' } }, '*');
  });
});
// Lets the page know the extension is installed (and new enough to arrange tabs)
document.documentElement.dataset.jobtrackerExtension = '1.1';
