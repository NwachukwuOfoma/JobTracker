// Runs only on LinkedIn job pages opened from the JobTracker dashboard
// (marked with #jobtracker-apply). It does what you'd do by hand: find the
// "Apply" button and follow it to the company's site. Nothing runs on
// LinkedIn pages you open yourself, and no extra requests are made.
(() => {
  const MARKER = '#jobtracker-apply';
  const KEY = 'jobtracker-apply';
  const TIMEOUT_MS = 15000;

  // LinkedIn may rewrite the URL after load, so remember the marker for this tab.
  if (location.hash === MARKER) sessionStorage.setItem(KEY, String(Date.now()));
  const started = Number(sessionStorage.getItem(KEY) || 0);
  if (!started || Date.now() - started > TIMEOUT_MS) return;

  const done = () => sessionStorage.removeItem(KEY);
  // LinkedIn wraps outside links in a /safety/go/?url=... interstitial, which
  // often fails to load when several jobs open at once; go to the real link.
  const unwrap = (url) => {
    try {
      const u = new URL(url, location.href);
      if (u.hostname.endsWith('linkedin.com') && u.pathname.startsWith('/safety/go') && u.searchParams.get('url')) {
        return u.searchParams.get('url');
      }
    } catch (e) { /* not a URL; use as is */ }
    return url;
  };
  const go = (url) => { done(); location.replace(unwrap(url)); };

  // LinkedIn opens the company site in a new tab; send it to this tab instead.
  const originalOpen = window.open;
  window.open = function (url, ...rest) {
    if (url && sessionStorage.getItem(KEY)) { go(String(url)); return null; }
    return originalOpen.call(window, url, ...rest);
  };

  const notice = (text) => {
    const el = document.createElement('div');
    el.textContent = text;
    el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:99999;padding:10px 14px;' +
      'border-radius:8px;background:#1f2937;color:#fff;font:14px system-ui;box-shadow:0 4px 12px rgba(0,0,0,.3)';
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  };

  const findApplyUrlInPage = () => {
    const m = document.documentElement.innerHTML.match(/"companyApplyUrl":"(https?:[^"]+)"/);
    return m ? JSON.parse('"' + m[1] + '"') : null;
  };

  const findApplyButton = () => {
    const candidates = document.querySelectorAll(
      '.jobs-apply-button, .jobs-s-apply button, button[aria-label*="Apply"], a[aria-label*="Apply"]'
    );
    return Array.from(candidates).find((el) => el.offsetParent !== null) || null;
  };

  let clicked = false;
  const tick = () => {
    if (!sessionStorage.getItem(KEY)) return;
    if (Date.now() - started > TIMEOUT_MS) {
      done();
      notice('JobTracker: couldn\'t find the company application link. Use the Apply button.');
      return;
    }

    const directUrl = findApplyUrlInPage();
    if (directUrl) return go(directUrl);

    // LinkedIn sometimes asks to share your profile before leaving; continue past it.
    const continueBtn = Array.from(document.querySelectorAll('[role="dialog"] button'))
      .find((b) => /^(continue|continue applying)$/i.test(b.innerText.trim()));
    if (continueBtn) continueBtn.click();

    const btn = findApplyButton();
    if (btn && !clicked) {
      if (/easy apply/i.test(btn.innerText) || /easy apply/i.test(btn.getAttribute('aria-label') || '')) {
        done();
        notice('JobTracker: this is an Easy Apply job, so it stays on LinkedIn.');
        return;
      }
      if (btn.tagName === 'A' && btn.href && !btn.href.startsWith(location.origin + location.pathname)) {
        return go(btn.href);
      }
      clicked = true;
      btn.click();
    }
    setTimeout(tick, 300);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(tick, 300));
  } else {
    setTimeout(tick, 300);
  }
})();
