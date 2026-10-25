// Placeholder for a job opened from the dashboard. The real page loads only when
// you switch to this tab, so opening dozens of jobs doesn't hit every site at once
// (which gets pages rate-limited into "This page isn't working").
const params = new URLSearchParams(location.search);
const target = params.get('url');
const label = params.get('title') || target;

document.title = `⏳ ${label}`;
document.getElementById('title').textContent = label;
if (params.get('fit')) document.getElementById('fit').textContent = `🎯 Fit ${params.get('fit')}`;

const open = () => {
  if (document.visibilityState === 'visible' && target) location.replace(target);
};
document.addEventListener('visibilitychange', open);
open();
