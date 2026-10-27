// Injected only when you click the JobTracker toolbar icon on an application page
// (into every frame, since forms like Greenhouse's are often embedded). Finds the
// open-ended questions, then drafts answers you review, edit and paste or fill in.
(() => {
  if (!window.__jobtrackerAnswers) {
    // Fields that are form data, not questions to write an answer for
    const SKIP = /\b(first|last|middle|full|legal|preferred)?\s*name\b|e-?mail|phone|mobile|linked\s?in|github|twitter|website|portfolio|\burl\b|address|city|state|zip|postal|country|location|salary|compensation|pronoun|school|university|degree|major|gpa|graduation|date|referr|how did you hear|resume|\bcv\b|cover letter|signature|initials/i;
    const OPEN_ENDED = /\?|\b(why|describe|explain|tell us|share|what|how|which|briefly|walk us)\b/i;

    const clean = (text) => (text || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim().slice(0, 700);

    function labelFor(field) {
      if (field.id) {
        const label = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
        if (label && clean(label.innerText)) return clean(label.innerText);
      }
      const labelledBy = field.getAttribute('aria-labelledby');
      if (labelledBy) {
        const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ');
        if (clean(text)) return clean(text);
      }
      if (clean(field.getAttribute('aria-label'))) return clean(field.getAttribute('aria-label'));
      const wrapping = field.closest('label');
      if (wrapping && clean(wrapping.innerText)) return clean(wrapping.innerText);
      // Otherwise the nearest container with its own text: the question sits just above the box
      let node = field.parentElement;
      for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
        const heading = node.querySelector('label, legend, h2, h3, h4, [class*="label" i], [class*="question" i], p');
        if (heading && !heading.contains(field) && clean(heading.innerText)) return clean(heading.innerText);
      }
      return clean(field.getAttribute('placeholder'));
    }

    function findQuestions() {
      const fields = [...document.querySelectorAll('textarea, input[type="text"], input:not([type])')];
      const found = [];
      for (const field of fields) {
        if (field.disabled || field.readOnly || !field.getClientRects().length) continue;
        // Dropdowns built from text boxes (Greenhouse, Workday) and their hidden twins
        if (field.getAttribute('role') === 'combobox' || field.hasAttribute('aria-autocomplete') ||
            field.getAttribute('aria-hidden') === 'true' || field.hasAttribute('list')) continue;
        const label = labelFor(field);
        if (!label || label.length < 8) continue;
        // Contact fields have short labels; a long question that mentions GitHub or a link still counts
        const isQuestion = label.length >= 50 && OPEN_ENDED.test(label);
        if (SKIP.test(label) && !isQuestion) continue;
        // Short text boxes count only when they're clearly asking something
        if (field.tagName !== 'TEXTAREA' && !(label.length >= 30 && OPEN_ENDED.test(label))) continue;
        if (found.some((q) => q.field === field)) continue;
        const max = Number(field.getAttribute('maxlength')) || null;
        found.push({ field, label, maxLength: max && max > 0 && max < 100000 ? max : null });
      }
      return found;
    }

    // Sets a value the way typing does, so React/Workday forms notice it
    function fill(field, value) {
      const proto = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.dispatchEvent(new Event('change', { bubbles: true }));
    }

    let host = null;
    let items = [];

    const CSS_TEXT = `
      :host { all: initial; }
      .panel { position: fixed; top: 12px; right: 12px; bottom: 12px; width: 400px; max-width: calc(100vw - 24px);
        z-index: 2147483647; display: flex; flex-direction: column; font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #ffffff; color: #1f2328; border: 1px solid #d0d7de; border-radius: 10px; box-shadow: 0 8px 30px rgba(0,0,0,.18); }
      header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #d0d7de; }
      header b { flex: 1; font-size: 14px; }
      .job { padding: 6px 12px; color: #59636e; font-size: 12px; border-bottom: 1px solid #eaeef2; }
      .list { flex: 1; overflow-y: auto; padding: 8px 12px 16px; }
      .q { border: 1px solid #d0d7de; border-radius: 8px; padding: 10px; margin-top: 10px; }
      .label { font-weight: 600; cursor: pointer; }
      .label:hover { text-decoration: underline; }
      .limit { color: #59636e; font-size: 11px; margin-top: 2px; }
      textarea { box-sizing: border-box; width: 100%; margin-top: 6px; padding: 6px 8px; font: inherit; color: inherit;
        background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; resize: vertical; }
      textarea.note { min-height: 34px; }
      textarea.answer { min-height: 90px; background: #ffffff; }
      .row { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
      .count { flex: 1; color: #59636e; font-size: 11px; }
      .count.over { color: #cf222e; font-weight: 600; }
      button { font: inherit; padding: 4px 10px; border-radius: 6px; border: 1px solid #d0d7de; background: #f6f8fa; color: inherit; cursor: pointer; }
      button:hover { background: #eaeef2; }
      button.primary { background: #1f6feb; border-color: #1f6feb; color: #ffffff; }
      button.primary:hover { background: #1a5fcc; }
      button:disabled { opacity: .55; cursor: default; }
      .status { padding: 8px 12px; color: #59636e; font-size: 12px; border-top: 1px solid #eaeef2; }
      .status.error { color: #cf222e; }
      .empty { color: #59636e; padding: 16px 0; }
      @media (prefers-color-scheme: dark) {
        .panel { background: #161b22; color: #e6edf3; border-color: #30363d; }
        header, .q { border-color: #30363d; }
        .job, .status { border-color: #21262d; color: #9198a1; }
        .limit, .count, .empty { color: #9198a1; }
        textarea, button { background: #21262d; border-color: #30363d; }
        textarea.answer { background: #0d1117; }
        button:hover { background: #30363d; }
      }`;

    function setStatus(text, isError) {
      const status = host.shadowRoot.querySelector('.status');
      status.textContent = text;
      status.classList.toggle('error', !!isError);
    }

    function updateCount(item) {
      const len = item.answer.value.length;
      item.count.textContent = item.maxLength ? `${len} / ${item.maxLength} characters` : `${len} characters`;
      item.count.classList.toggle('over', !!item.maxLength && len > item.maxLength);
    }

    function draft(targets) {
      const buttons = host.shadowRoot.querySelectorAll('button');
      buttons.forEach((b) => { b.disabled = true; });
      setStatus(`Drafting ${targets.length === 1 ? 'an answer' : `${targets.length} answers`}…`);
      const questions = targets.map((item) => ({
        label: item.label,
        max_length: item.maxLength,
        note: item.note.value.trim(),
        previous: item.redo ? item.answer.value.trim() : '',
      }));
      chrome.runtime.sendMessage({
        type: 'draft-answers',
        frameUrl: location.href,
        title: document.title,
        pageText: (document.body?.innerText || '').slice(0, 8000),
        questions,
      }, (result) => {
        buttons.forEach((b) => { b.disabled = false; });
        if (!result || result.error) {
          setStatus(result?.error || 'No response. Is the JobTracker server running?', true);
          return;
        }
        targets.forEach((item, i) => {
          item.answer.value = result.answers[i] || '';
          item.redo = false;
          updateCount(item);
        });
        if (result.job) host.shadowRoot.querySelector('.job').textContent = `Matched job: ${result.job}`;
        setStatus('Review each answer, then Copy or Fill. Anything in [add: …] needs a detail from you.');
      });
    }

    function render() {
      items = findQuestions().map((q) => ({ ...q, redo: false }));
      if (!host) {
        host = document.createElement('div');
        host.id = 'jobtracker-answers';
        host.attachShadow({ mode: 'open' });
        document.documentElement.appendChild(host);
      }
      const root = host.shadowRoot;
      root.innerHTML = `<style>${CSS_TEXT}</style>
        <div class="panel" role="dialog" aria-label="JobTracker answers">
          <header><b>Application answers</b>
            <button class="rescan" title="Look for questions again (e.g. after moving to the next page of the form)">Rescan</button>
            <button class="primary all">Draft all</button>
            <button class="close" aria-label="Close">✕</button></header>
          <div class="job">${items.length} open-ended question${items.length === 1 ? '' : 's'} on this page</div>
          <div class="list"></div>
          <div class="status">Add a note to steer any answer (e.g. "say it was my Chimagine app"), then Draft all.</div>
        </div>`;
      const list = root.querySelector('.list');
      if (!items.length) {
        list.innerHTML = '<div class="empty">No open-ended questions found here. If the form has more pages, go to the next one and press Rescan.</div>';
      }
      for (const item of items) {
        const box = document.createElement('div');
        box.className = 'q';
        const label = document.createElement('div');
        label.className = 'label';
        label.textContent = item.label;
        label.title = 'Scroll to this question';
        label.addEventListener('click', () => item.field.scrollIntoView({ behavior: 'smooth', block: 'center' }));
        box.appendChild(label);
        if (item.maxLength) {
          const limit = document.createElement('div');
          limit.className = 'limit';
          limit.textContent = `Limit: ${item.maxLength} characters`;
          box.appendChild(limit);
        }
        item.note = document.createElement('textarea');
        item.note.className = 'note';
        item.note.placeholder = 'Your note (optional): what to say or focus on';
        item.answer = document.createElement('textarea');
        item.answer.className = 'answer';
        item.answer.placeholder = 'The draft appears here; you can edit it.';
        item.answer.addEventListener('input', () => updateCount(item));
        const row = document.createElement('div');
        row.className = 'row';
        item.count = document.createElement('span');
        item.count.className = 'count';
        const redo = document.createElement('button');
        redo.textContent = 'Redo';
        redo.title = 'Draft this one again (uses your note, and avoids the current draft)';
        redo.addEventListener('click', () => { item.redo = !!item.answer.value.trim(); draft([item]); });
        const copy = document.createElement('button');
        copy.textContent = 'Copy';
        copy.addEventListener('click', async () => {
          await navigator.clipboard.writeText(item.answer.value);
          copy.textContent = 'Copied';
          setTimeout(() => { copy.textContent = 'Copy'; }, 1200);
        });
        const fillButton = document.createElement('button');
        fillButton.textContent = 'Fill';
        fillButton.title = 'Put this answer into the form field';
        fillButton.addEventListener('click', () => {
          fill(item.field, item.answer.value);
          item.field.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        row.append(item.count, redo, copy, fillButton);
        box.append(item.note, item.answer, row);
        list.appendChild(box);
        updateCount(item);
      }
      root.querySelector('.close').addEventListener('click', () => { host.remove(); host = null; });
      root.querySelector('.rescan').addEventListener('click', render);
      const all = root.querySelector('.all');
      all.disabled = !items.length;
      all.addEventListener('click', () => draft(items));
    }

    window.__jobtrackerAnswers = {
      count: () => findQuestions().length,
      open: render,
      isOpen: () => !!host,
      close: () => { host?.remove(); host = null; },
    };
  }
  return window.__jobtrackerAnswers.count();
})();
