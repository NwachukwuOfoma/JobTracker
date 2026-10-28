// Injected only when you click the JobTracker toolbar icon on an application page
// (into every frame, since forms like Greenhouse's are often embedded). Finds the
// open-ended questions, then drafts answers you review, edit and paste or fill in.
(() => {
  if (!window.__jobtrackerAnswers) {
    // Reloading the extension cuts panels already open on pages off from it ("Extension
    // context invalidated"). A cut-off panel says so instead of throwing errors.
    const STALE = 'JobTracker was updated or reloaded. Refresh this page to use the new version.';
    const alive = () => { try { return !!chrome.runtime?.id; } catch (e) { return false; } };
    function send(message, callback) {
      if (!alive()) {
        observer?.disconnect();
        observer = null;
        callback?.({ error: STALE });
        return;
      }
      chrome.runtime.sendMessage(message, callback);
    }
    // Fields that are form data, not questions to write an answer for
    const SKIP = /\b(first|last|middle|full|legal|preferred)?\s*name\b|e-?mail|phone|mobile|linked\s?in|github|twitter|website|portfolio|\burl\b|address|city|state|zip|postal|country|location|salary|compensation|pronoun|school|university|degree|major|gpa|graduation|date|referr|how did you hear|resume|\bcv\b|cover letter|signature|initials/i;
    const OPEN_ENDED = /\?|\b(why|describe|explain|tell us|share|what|how|which|briefly|walk us)\b/i;
    // Short questions that want a number ("How many years of experience do you have?")
    const NUMERIC = /^(how many|number of)\b|\byears of (\S+ )?(work |professional |industry )?experience do you have\b/i;

    const clean = (text) => (text || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim().slice(0, 700);

    // Some forms (SmartRecruiters) build their fields inside web components' shadow
    // DOM, which ordinary queries don't reach. These look inside open shadow roots
    // (never this panel's own) and step back out to the host when walking up.
    function deepAll(selector, root = document) {
      const found = [...root.querySelectorAll(selector)];
      for (const el of root.querySelectorAll('*')) {
        if (el.shadowRoot && el.id !== 'jobtracker-answers') found.push(...deepAll(selector, el.shadowRoot));
      }
      return found;
    }
    const up = (el) => el.parentElement || el.parentNode?.host || null;
    const FIELDS = 'input, select, textarea';
    const fieldsIn = (n) => [...deepAll(FIELDS, n), ...(n.shadowRoot ? deepAll(FIELDS, n.shadowRoot) : [])];
    function closestDeep(el, selector) {
      for (let node = el; node; node = up(node)) if (node.matches?.(selector)) return node;
      return null;
    }
    // Ids and label[for] are looked up in the field's own (shadow) root first
    const inRoot = (el, selector) => el.getRootNode().querySelector?.(selector) || document.querySelector(selector);
    const byId = (el, id) => el.getRootNode().getElementById?.(id) || document.getElementById(id);
    // Text as shown, including what components render inside their shadow roots
    function deepText(node) {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (!node.childNodes || node.matches?.('script, style')) return '';
      if (node.localName === 'slot') return node.assignedNodes({ flatten: true }).map(deepText).join(' ');
      const children = node.shadowRoot ? node.shadowRoot.childNodes : node.childNodes;
      const text = [...children].map(deepText).join(' ');
      return /^(p|div|li|label|legend|h\d|br|tr)$/.test(node.localName || '') ? `${text}\n` : text;
    }

    function labelFor(field) {
      if (field.id) {
        const label = inRoot(field, `label[for="${CSS.escape(field.id)}"]`);
        if (label && clean(label.innerText)) return clean(label.innerText);
      }
      const labelledBy = field.getAttribute('aria-labelledby');
      if (labelledBy) {
        const text = labelledBy.split(/\s+/).map((id) => byId(field, id)?.innerText || '').join(' ');
        if (clean(text)) return clean(text);
      }
      if (clean(field.getAttribute('aria-label'))) return clean(field.getAttribute('aria-label'));
      const wrapping = closestDeep(field, 'label');
      if (wrapping && clean(wrapping.innerText)) return clean(wrapping.innerText);
      // Otherwise the nearest container with its own text: the question sits just above the box
      let node = up(field);
      for (let depth = 0; node && depth < 5; depth++, node = up(node)) {
        // Components often take their label as an attribute (<spl-input label="Email">)
        if (node !== field && node.localName?.includes('-') && clean(node.getAttribute('label'))) return clean(node.getAttribute('label'));
        const heading = node.querySelector?.('label, legend, h2, h3, h4, [class*="label" i], [class*="question" i], p');
        if (heading && !heading.contains(field) && clean(heading.innerText)) return clean(heading.innerText);
      }
      return clean(field.getAttribute('placeholder'));
    }

    function findQuestions() {
      const fields = deepAll('textarea, input[type="text"], input:not([type])');
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
        if (label.length < 120 && NUMERIC.test(label)) continue;
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
      field.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      field.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      // Some date pickers (SmartRecruiters) only commit typed text when the box loses focus
      field.dispatchEvent(new Event('blur', { composed: true }));
    }

    // ---- Fill rest: the form's other blanks (resume, dropdowns, yes/no questions,
    // checkboxes, short fields), matched to your standard answers by the rules below.
    // No API calls, so it costs nothing.

    // React dropdowns are read and set by page_select.js in the page's own world;
    // the event round trip is synchronous, so the result is ready on return
    let nextId = 0;
    function pageSelect(action, el, value) {
      if (!el.dataset.jtId) el.dataset.jtId = `jt${nextId++}`;
      const id = el.dataset.jtId;
      let result = null;
      const listener = (e) => { const d = JSON.parse(e.detail); if (d.id === id) result = d.result; };
      document.addEventListener('jobtracker-select-result', listener);
      document.dispatchEvent(new CustomEvent('jobtracker-select', { detail: JSON.stringify({ action, id, value }) }));
      document.removeEventListener('jobtracker-select-result', listener);
      return result;
    }
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    // Custom-styled radios and checkboxes often hide the input and show its label
    const shown = (el) => !!el && (!!el.getClientRects().length ||
      !!(el.id && inRoot(el, `label[for="${CSS.escape(el.id)}"]`)?.getClientRects().length) ||
      !!closestDeep(el, 'label')?.getClientRects().length);

    function optionText(input) {
      const label = (input.id && inRoot(input, `label[for="${CSS.escape(input.id)}"]`)) || closestDeep(input, 'label');
      return clean(label?.innerText || input.getAttribute('aria-label') || input.value || input.textContent);
    }

    // One question's block on the page (Ashby's fieldEntry, a fieldset, a role=group)
    const ENTRY = 'fieldset, [role="radiogroup"], [role="group"], [class*="fieldEntry" i], [class*="field-entry" i]';

    // The question above a group of options: its legend, its ARIA label, or the text
    // of the nearest container holding the whole group, minus the options' own labels
    // `related` are the group's own hidden companions (Ashby keeps a hidden checkbox
    // beside its Yes/No buttons): they belong to this question, not another one
    function groupLabel(inputs, related = []) {
      const legend = closestDeep(inputs[0], 'fieldset')?.querySelector('legend');
      if (legend && clean(legend.innerText)) return clean(legend.innerText);
      const group = closestDeep(inputs[0], '[role="radiogroup"], [role="group"]');
      const labelledBy = group?.getAttribute('aria-labelledby');
      if (labelledBy) {
        const text = clean(labelledBy.split(/\s+/).map((id) => byId(inputs[0], id)?.innerText || '').join(' '));
        if (text) return text;
      }
      if (clean(group?.getAttribute('aria-label'))) return clean(group.getAttribute('aria-label'));
      const optionTexts = inputs.map(optionText).filter(Boolean);
      const within = (node, el) => { for (let n = el; n; n = up(n)) if (n === node) return true; return false; };
      let node = up(inputs[0]);
      for (let depth = 0; node && depth < 8; depth++, node = up(node)) {
        if (![...inputs, ...related].every((i) => within(node, i))) continue;
        // Past this point the text belongs to other questions too
        if (fieldsIn(node).some((f) => !inputs.includes(f) && !related.includes(f) && f.type !== 'hidden')) break;
        let text = deepText(node);
        for (const option of optionTexts) text = text.replace(option, ' ');
        if (clean(text).length >= 3) return clean(text).slice(0, 300);
      }
      return '';
    }

    // Required questions left unanswered get outlined; optional ones are just skipped.
    // Required shows as the attribute, or an asterisk on the question's own label.
    function isRequired(blank) {
      const target = blank.target;
      const own = target.matches('input, select, textarea') ? target : target.querySelector('input, select, textarea');
      const fields = [blank.field, blank.input, own, ...(blank.inputs || [])].filter(Boolean);
      if (fields.some((f) => f.required || f.getAttribute('aria-required') === 'true')) return true;
      for (const field of fields) {
        const label = field.id && inRoot(field, `label[for="${CSS.escape(field.id)}"]`);
        if (label && /[*✱]/.test(label.innerText)) return true;
      }
      const box = closestDeep(target, ENTRY) || up(target);
      // A form-wide note ("Fields marked with * are required") doesn't make this field required
      const text = (box ? deepText(box).slice(0, 400) : '')
        .replace(/(fields?|questions?) (marked|indicated) (with )?(an? )?(asterisk|\*)[^.\n]*/gi, '')
        .replace(/\*\s*(indicates|denotes|means)[^.\n]*/gi, '');
      return /[*✱]|required/i.test(text);
    }

    function findBlanks() {
      const written = new Set(findQuestions().map((q) => q.field));
      const blanks = [];
      const add = (blank) => { if (blank.label) blanks.push({ ...blank, required: isRequired(blank) }); };

      // Yes/No button pairs (Ashby): unanswered while neither is pressed
      const pairs = new Map();
      for (const button of deepAll('button')) {
        if (!/^(yes|no)$/i.test(clean(button.textContent)) || !shown(button)) continue;
        if (!pairs.has(up(button))) pairs.set(up(button), []);
        pairs.get(up(button)).push(button);
      }
      const pairEntries = [];
      for (const [parent, buttons] of pairs) {
        if (buttons.length < 2) continue;
        const entry = closestDeep(parent, ENTRY) || up(parent);
        pairEntries.push(entry);
        if (buttons.some((b) => b.getAttribute('aria-pressed') === 'true' || /active|selected/i.test(b.className))) continue;
        add({
          kind: 'choice', label: groupLabel(buttons, entry ? deepAll('input', entry) : []), options: buttons.map((b) => clean(b.textContent)), target: parent,
          apply: (value) => { const b = buttons.find((x) => clean(x.textContent) === value); b?.click(); return !!b; },
        });
      }

      const US = /united states|\busa?\b|\(\+1\)|^\+1\b/i;
      for (const select of deepAll('select')) {
        if (select.disabled || !shown(select)) continue;
        const options = [...select.options].filter((o) => o.value !== '' && !/^\s*(select|choose|--|please)/i.test(o.text));
        let phoneCountry = false;
        for (let n = up(select), i = 0; n && i < 4 && !phoneCountry; n = up(n), i++) {
          phoneCountry = options.some((o) => US.test(o.text)) && fieldsIn(n).some((f) => f.type === 'tel');
        }
        const chosen = select.selectedOptions[0];
        if (!options.length || (options.includes(chosen) && !(phoneCountry && !US.test(chosen.text)))) continue;
        add({
          kind: 'choice', label: phoneCountry ? 'Phone country code' : labelFor(select), options: options.map((o) => clean(o.text)), target: select,
          apply: (value) => {
            const option = options.find((o) => clean(o.text) === value);
            if (!option) return false;
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, option.value);
            select.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            select.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
            return true;
          },
        });
      }

      // Radio and checkbox groups, grouped by the question block they sit in (some forms
      // reuse one name across several questions)
      const groups = new Map();
      for (const input of deepAll('input[type="radio"], input[type="checkbox"]')) {
        if (input.disabled || !shown(input) || pairEntries.some((entry) => entry && closestDeep(input, ENTRY) === entry)) continue;
        const key = closestDeep(input, ENTRY) || (input.name ? `${input.type}:${input.name}` : input);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(input);
      }
      for (const inputs of groups.values()) {
        if (inputs.some((i) => i.checked)) continue;
        const target = closestDeep(inputs[0], ENTRY) || up(inputs[0]);
        if (inputs.length === 1 && inputs[0].type === 'checkbox') {
          const box = inputs[0];
          add({
            kind: 'checkbox', label: optionText(box).length >= 8 ? optionText(box) : clean(`${groupLabel(inputs)} ${optionText(box)}`),
            options: ['checked', 'unchecked'], target, inputs,
            apply: (value) => { if (value === 'checked' && !box.checked) box.click(); return true; },
          });
        } else {
          add({
            kind: 'choice', label: groupLabel(inputs), options: inputs.map(optionText), target, inputs,
            apply: (value) => { const input = inputs.find((i) => optionText(i) === value); input?.click(); return !!input; },
          });
        }
      }

      // Comboboxes: React dropdowns with their options, or search boxes (location)
      for (const input of deepAll('input[role="combobox"]')) {
        // A dropdown's own filter box ("Search by country/region or code") isn't a question
        if (!shown(input) || /^search\b/i.test(labelFor(input) || input.placeholder || '')) continue;
        const state = pageSelect('state', input);
        const target = closestDeep(input, '[class*="control"]') || input;
        if (state && !state.empty) continue;
        if (!state && input.value) continue;
        if (state && state.options.length) {
          add({ kind: 'choice', label: labelFor(input), options: state.options, target, apply: (value) => !!pageSelect('choose', input, value) });
        } else if (/location|city|where (are you|do you live)|school|university|college|degree|country|dial|phone/i.test(labelFor(input))) {
          add({ kind: 'search', label: labelFor(input), options: [], target, input, react: !!state });
        }
      }

      // Custom (non-<select>) country-code dropdowns beside a phone box, as on SmartRecruiters
      for (const tel of deepAll('input[type="tel"]')) {
        if (!shown(tel)) continue;
        // Only within the phone box's own small group, and never another labeled field
        // (Ashby's Location search box sits near its phone box)
        const TRIGGER = '[role="combobox"], [aria-haspopup="listbox"], [aria-haspopup="true"]';
        // A picker labeled as one ("Country code" on SmartRecruiters) can sit many levels away
        let trigger = deepAll(TRIGGER).find((el) => el.tagName !== 'INPUT' && shown(el) &&
          /country code|dial(ing)? code|calling code|phone code/i.test(`${el.getAttribute('aria-label') || ''} ${labelFor(el)}`)) || null;
        for (let n = up(tel), i = 0; n && i < 8 && !trigger && fieldsIn(n).length <= 3; n = up(n), i++) {
          trigger = [...deepAll(TRIGGER, n), ...(n.shadowRoot ? deepAll(TRIGGER, n.shadowRoot) : [])]
            .find((el) => el !== tel && el.tagName !== 'SELECT' && shown(el) &&
              (el.tagName !== 'INPUT' || /code|country|dial|phone/i.test(labelFor(el)))) || null;
        }
        if (!trigger || US.test(`${deepText(trigger)} ${trigger.value || ''}`) || /\+\s?1\b(?!\d)/.test(deepText(trigger))) continue;
        add({ kind: 'dropdown', label: 'Phone country code', options: [], target: trigger, trigger });
      }

      const textFields = 'input[type="text"], input[type="email"], input[type="url"], input[type="tel"], input[type="number"], input[type="date"], input[type="month"], input:not([type])';
      for (const field of deepAll(textFields)) {
        if (written.has(field) || field.value || field.disabled || field.readOnly || !shown(field)) continue;
        if (field.getAttribute('role') === 'combobox' || field.hasAttribute('aria-autocomplete') || field.getAttribute('aria-hidden') === 'true') continue;
        const label = labelFor(field);
        if (label.length < 2) continue; // short labels are real: "To" on an education date
        add({
          kind: 'text', label, options: [], target: field, field,
          apply: (value) => {
            // Date boxes only take YYYY-MM-DD (month boxes YYYY-MM); "Immediately" can't go in one
            if (field.type === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
            if (field.type === 'month' && !/^\d{4}-\d{2}$/.test(value)) return false;
            fill(field, value);
            return true;
          },
        });
      }
      return blanks;
    }

    // The rules: each matches a question's wording and picks an option (or text) from
    // your profile. The first matching rule decides; no match leaves the field for you.
    const DECLINE = [/prefer not|decline|don.?t wish|do not wish|not (to )?(answer|say|disclose|specify)|rather not/i];
    function pick(options, patterns) {
      for (const pattern of patterns) {
        const option = options.find((o) => pattern.test(o));
        if (option) return option;
      }
      return '';
    }
    const Y = (b) => (b.kind === 'checkbox' ? 'checked' : b.kind === 'text' ? 'Yes'
      : pick(b.options, [/^yes\b/i, /^(i am|i'm|i do|i have|i can|i will)\b(?!.*\bnot\b)/i, /^(true|agree|accept)/i]));
    const N = (b) => (b.kind === 'checkbox' ? 'unchecked' : b.kind === 'text' ? 'No'
      : pick(b.options, [/^no\b/i, /\b(not|never|don.?t|do not|haven.?t|have not|won.?t|will not|am not)\b/i]));
    const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    function rangeOption(options, value) {
      for (const option of options) {
        const nums = (option.replace(/,/g, '').match(/\d+(\.\d+)?\s*k?/gi) || []).map((n) => parseFloat(n) * (/k/i.test(n) ? 1000 : 1));
        if (!nums.length) continue;
        if (/under|younger|less than|below|up to/i.test(option) && nums.length === 1) { if (value < nums[0]) return option; continue; }
        if (/over|older|more|above|\+/i.test(option) && nums.length === 1) { if (value >= nums[0]) return option; continue; }
        if (nums.length >= 2 && value >= nums[0] && value <= nums[1]) return option;
      }
      return '';
    }

    // Age today from a YYYY-MM-DD birthday, so age-range answers stay right every year
    function ageFrom(birthDate) {
      const [y, m, d] = (birthDate || '').split('-').map(Number);
      if (!y) return NaN;
      const now = new Date();
      return now.getFullYear() - y - (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d) ? 1 : 0);
    }

    // The education entry a field belongs to: the one whose school is named nearby
    // (typed or shown), else by order (the nth "School" field gets the nth entry)
    function educationFor(b, P) {
      const list = P.education || [];
      if (!list.length) return null;
      let node = b.target;
      for (let i = 0; i < 6 && node; i++, node = up(node)) {
        const fields = fieldsIn(node);
        if (fields.length > 14) break;
        const seen = `${deepText(node)} ${fields.map((f) => (f.tagName === 'SELECT' ? f.selectedOptions[0]?.text : f.value) || '').join(' ')}`.toLowerCase();
        const hit = list.find((e) => seen.includes(e.school.toLowerCase().split(' ').slice(0, 2).join(' ')));
        if (hit) return hit;
      }
      const el = b.field || b.input || b.target;
      const same = deepAll(FIELDS).filter((f) => labelFor(f) === b.label);
      return list[Math.min(Math.max(0, same.indexOf(el)), list.length - 1)];
    }
    // Is this field part of an education entry? Its label says so, or the smallest
    // group of fields around it (one entry, not the whole form) has a school field.
    function inEducation(b) {
      if (/school|university|college|degree|education|institution|major|field of study/i.test(b.label)) return true;
      for (let node = up(b.target), i = 0; node && i < 8; node = up(node), i++) {
        const fields = fieldsIn(node);
        if (fields.length > 10) return false; // that's the whole form, not one entry
        if (fields.some((f) => /school|university|college|institution/i.test(labelFor(f)))) return true;
      }
      return false;
    }
    const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
    // An education start/end date, written the way this field wants it
    function educationDate(b, P) {
      const which = /\b(from|start|begin|began|entry)\b/i.test(b.label) ? 'start'
        : /\b(to|end|until|finish|graduat|completion|completed)\b/i.test(b.label) ? 'end' : null;
      if (!which || !inEducation(b)) return null;
      const entry = educationFor(b, P);
      if (!entry?.[which]) return null;
      const [y, m] = entry[which].split('-');
      if (b.kind === 'choice' || b.kind === 'search') {
        // Separate month and year dropdowns
        const month = pick(b.options, [new RegExp(`^${MONTHS[m - 1]}`, 'i'), new RegExp(`^0?${Number(m)}$`)]);
        return /year/i.test(b.label) || b.options.some((o) => o === y) ? pick(b.options, [new RegExp(`^${y}$`)]) : month;
      }
      const field = b.field;
      if (field?.type === 'month') return `${y}-${m}`;
      if (field?.type === 'date') return `${y}-${m}-01`;
      const hint = `${field?.placeholder || ''} ${b.label}`.toLowerCase();
      if (/\byear\b/.test(b.label.toLowerCase()) && !/month/.test(b.label.toLowerCase())) return y;
      if (/\bmonth\b/.test(b.label.toLowerCase()) && !/year/.test(b.label.toLowerCase())) return m;
      if (/mm\s*\/\s*dd\s*\/\s*yyyy/.test(hint)) return `${m}/01/${y}`;
      if (/yyyy\s*-\s*mm/.test(hint)) return `${y}-${m}`;
      if (/mm\s*\/\s*yy(?!yy)\b/.test(hint)) return `${m}/${y.slice(2)}`;
      return `${m}/${y}`;
    }

    function rules(P) {
      const worksHere = () => (P.past_employers || []).some((e) => new RegExp(`\\b${escapeRe(e)}\\b`, 'i').test(`${document.title} ${location.hostname}`));
      // A null answer means "not this rule": the next matching rule gets a turn
      const text = (value) => (b) => (b.kind === 'text' || b.kind === 'search' ? value : null);
      return [
        // Opt-ins come before consents, since "I agree to receive texts" is an opt-in
        [/\b(sms|text messages?|whatsapp|marketing|newsletter|promotional|talent (community|network)|future (job )?opportunit|job alerts?)\b/, N],
        [/sponsor|visa|h-?1b|immigration/, N],
        [/authori[sz]ed|eligible to work|legally (able|permitted)|right to work|work permit|employment eligib/, Y],
        [/\b(usa|u\.s\.) citizen|citizenship/, (b) => pick(b.options, [/^yes\b/i, /^usa?$|united states|u\.s\./i])],
        [/relocat/, Y],
        [/18 years|at least 18|over 18|age of 18|legal (working )?age/, Y],
        [/date of birth|birth ?date|birthday|\bdob\b/, (b) => {
          if (b.kind !== 'text' || !P.birth_date) return '';
          const [y, m, d] = P.birth_date.split('-');
          return b.field.type === 'date' ? P.birth_date : `${m}/${d}/${y}`;
        }],
        [/current age|your age|age range|how old/, (b) => rangeOption(b.options, ageFrom(P.birth_date)) || pick(b.options, DECLINE)],
        [/clearance/, (b) => (/eligib|able to obtain|willing to (obtain|undergo)|could you obtain/i.test(b.label) ? Y(b)
          : pick(b.options, [/^no\b/i, /none|not currently|do not (currently )?hold|don.?t have/i]))],
        [/background check|drug (test|screen)|screening/, Y],
        [/non-?compete|restrictive covenant|non-?solicit|agreements? that (would|could|might) (restrict|prevent|limit)|bound by/, N],
        [/hybrid|in[- ]office|on[- ]?site|commute|work (out )?of our|times a week|days a week|from (our|the) office|in person/, Y],
        [/(have you|ever) (previously |ever )?(worked|been employed)|previous(ly)? (employ|work)|former employee|current(ly)? (an? )?employ|are you a current/,
          (b) => (worksHere() ? Y(b) : N(b))],
        [/relative|family member|friends? (who )?work|related to anyone|know anyone/, N],
        [/how did you (hear|find|learn)|where did you (hear|find|see|learn)|referral source|source of (this )?application|how were you referred/,
          (b) => (b.kind === 'text' ? 'GitHub job board' : pick(b.options, (P.hear_about || []).map((h) => new RegExp(escapeRe(h), 'i'))))],
        [/transgender/, (b) => pick(b.options, DECLINE)],
        [/sexual orientation/, (b) => (P.sexual_orientation === 'straight' ? pick(b.options, [/heterosexual|straight/i]) : '') || pick(b.options, DECLINE)],
        [/hispanic|latin[oaxe]/, (b) => (P.hispanic ? Y(b) : pick(b.options, [/^no\b/i, /not hispanic/i]))],
        [/\brace\b|ethnic/, (b) => pick(b.options, [new RegExp(escapeRe(P.race.split(' ')[0]), 'i')]) || pick(b.options, DECLINE)],
        [/gender|\bsex\b/, (b) => pick(b.options, P.gender === 'male' ? [/^(male|man)\b/i] : [/^(female|woman)\b/i]) || pick(b.options, DECLINE)],
        [/veteran/, (b) => (P.veteran ? Y(b) : pick(b.options, [/not a (protected )?veteran|i am not/i, /^no\b/i]))],
        [/disabilit/, (b) => (P.disability ? Y(b) : pick(b.options, [/^no\b|do(n.?t| not) have a disability/i])) || pick(b.options, DECLINE)],
        [/communit|belong to/, (b) => pick(b.options, [/none of the above/i]) || pick(b.options, DECLINE)],
        [/pronoun/, () => ''],
        [/\bgpa\b|grade point/, () => ''],
        [/\b(from|to|start|end|begin|until|finish|graduat\w*|completion|month|year|dates?)\b/, (b) => educationDate(b, P)],
        [/currently (attend|enrolled|studying|a student)|still (attend|enrolled)/, (b) => (b.kind === 'checkbox' ? 'unchecked' : null)],
        [/enrolled|graduat|currently a student/, (b) => pick(b.options, [/already graduated|^graduated|not (currently )?(enrolled|a student)|alumn/i])],
        [/start date|start working|available to start|earliest|notice period/, (b) => (b.kind === 'text' ? P.start_date
          : pick(b.options, [/immediate|asap|right away|^now/i, /2 weeks|two weeks/i]))],
        [/salary|compensation|pay (expectation|range|requirement)|desired pay|expected pay/, (b) => (b.kind === 'text'
          ? (b.field?.type === 'number' || /number|numeric|annual|usd|\$|amount/i.test(b.label) ? P.salary_number : P.salary_text)
          : rangeOption(b.options, Number(P.salary_number)))],
        // Consent applies to checkboxes and choices; a text box like "Confirm your email" falls through
        [/acknowledg|consent|agree|certif|attest|confirm|privacy|terms|accurate|read and understand/, (b) => (b.kind === 'text' ? null : Y(b))],
        // Contact and background details
        [/preferred (first )?name|first name|given name/, text(P.first_name)],
        [/last name|surname|family name/, text(P.last_name)],
        [/full name|legal name|^name\b|your name/, text(`${P.first_name} ${P.last_name}`)],
        [/e-?mail/, text(P.email)],
        [/phone|mobile|cell/, text(P.phone)],
        [/linkedin/, text(P.linkedin)],
        [/github/, text(P.github)],
        [/website|portfolio|personal (site|url)/, text(P.website)],
        [/\bcountry\b|country code|dial(ing)? code|phone (country|code)/, (b) => (b.kind === 'text' || b.kind === 'search' || b.kind === 'dropdown' ? P.country
          : pick(b.options, [/^united states\b/i, /\bunited states\b/i, /^usa?\b|\bu\.s\.a?\b/i, /\(\+1\)|^\+1\b/]))],
        [/\b(state|province)\b/, (b) => (b.kind === 'text' ? P.state : pick(b.options, [new RegExp(`^${escapeRe(P.state)}`, 'i'), /^il$/i]))],
        [/\bcity\b|location|located|where (are you|do you live)|current address|based in/, (b) => (b.kind === 'text' || b.kind === 'search'
          ? (b.kind === 'search' || /\bcity\b/i.test(b.label) ? P.city : P.location) : '')],
        [/school|university|college|institution/, (b) => {
          const entry = educationFor(b, P) || { school: P.school };
          return b.kind === 'choice' ? pick(b.options, [new RegExp(escapeRe(entry.school.split(' ').slice(0, 2).join(' ')), 'i')]) : entry.school;
        }],
        [/degree/, (b) => {
          const entry = educationFor(b, P) || { degree: P.degree, level: 'master' };
          const level = entry.level === 'bachelor' ? /bachelor|b\.?s\b|undergrad/i : /master|m\.?s\b|m\.?eng/i;
          return b.kind === 'text' ? entry.degree : b.kind === 'search' ? (entry.level === 'bachelor' ? 'Bachelor' : 'Master') : pick(b.options, [level]);
        }],
      ];
    }

    function answerFor(blank, P) {
      // "United States" would otherwise trip the state rule
      const question = blank.label.toLowerCase().replace(/united states/g, 'usa');
      for (const [pattern, decide] of rules(P)) {
        if (!pattern.test(question)) continue;
        const answer = decide(blank);
        if (answer !== null) return answer || '';
      }
      return '';
    }

    // Custom dropdowns: open the menu, then click the matching option
    async function fillDropdown(blank, value) {
      const open = (el) => {
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, composed: true }));
        el.click();
      };
      open(blank.trigger);
      await sleep(600);
      // Option text can come in through slots (SmartRecruiters draws each option inside
      // nested components), so read it as shown, from the option or the element around it
      const textOf = (o) => {
        for (let node = o, i = 0; node && i < 4; node = up(node), i++) {
          const text = clean(deepText(node));
          if (text) return text;
        }
        return '';
      };
      const options = deepAll('[role="option"]').filter((o) => o.getClientRects().length);
      // A country code ("US") on the option or its host is the surest match
      let option = /united states/i.test(value) ? options.find((o) => closestDeep(o, '[value]')?.getAttribute('value') === 'US') : null;
      if (!option) {
        const prefer = [new RegExp(`^${escapeRe(value)}(\\s*\\+\\s*\\d+)?$`, 'i'), new RegExp(`^${escapeRe(value)}\\b`, 'i'), new RegExp(`\\b${escapeRe(value)}\\b`, 'i')];
        if (/united states/i.test(value)) prefer.push(/\busa?\b/i);
        const text = pick(options.map(textOf), prefer);
        option = options.find((o) => textOf(o) === text);
      }
      if (!option) {
        blank.trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, composed: true }));
        return false;
      }
      option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, composed: true }));
      option.click();
      await sleep(300);
      return true;
    }

    // Location search boxes: type the city, then pick the matching suggestion
    async function fillSearch(blank, value) {
      const prefer = [new RegExp(`${escapeRe(value)}.*(${escapeRe(profile.state)}|, il\\b)`, 'i'), new RegExp(`^${escapeRe(value)}`, 'i'),
        new RegExp(escapeRe(value), 'i')];
      if (blank.react) {
        pageSelect('search', blank.input, value);
        await sleep(1500);
        const option = pick(pageSelect('state', blank.input)?.options || [], prefer);
        const chosen = !!option && !!pageSelect('choose', blank.input, option);
        pageSelect('close', blank.input);
        return chosen;
      }
      fill(blank.input, value);
      await sleep(1500);
      const options = deepAll('[role="option"]').filter((o) => o.getClientRects().length);
      const text = pick(options.map((o) => clean(o.textContent)), prefer);
      const option = options.find((o) => clean(o.textContent) === text);
      option?.click();
      return !!option;
    }

    // Attaches your newest resume to the form's resume upload. Uploads labeled as a
    // resume or CV come first; otherwise the first upload that isn't for another kind of
    // document (some forms just say "Upload"). Returns 'attached', 'already' or 'none'.
    async function attachResume() {
      const empty = deepAll('input[type="file"]').filter((input) => !input.files.length).map((input) => {
        const box = closestDeep(input, ENTRY) || up(up(input) || input);
        return { input, context: `${input.name} ${input.id} ${input.getAttribute('aria-label') || ''} ${labelFor(input)} ${box ? deepText(box).slice(0, 200) : ''}` };
      });
      const otherDocument = /cover|transcript|portfolio|writing sample|additional|other document|photo|headshot|certificat/i;
      let uploads = empty.filter((u) => /resume|\bcv\b|résumé/i.test(u.context) && !otherDocument.test(u.context));
      if (!uploads.length) uploads = empty.filter((u) => !otherDocument.test(u.context)).slice(0, 1);
      if (!uploads.length) return deepAll('input[type="file"]').some((input) => input.files.length) ? 'already' : 'none';
      const resume = await new Promise((resolve) => send({ type: 'get-resume' }, resolve));
      if (!resume || resume.error) return 'none';
      // Forms that move the file elsewhere after an upload show its name instead
      if (deepText(document.body).includes(resume.name.replace(/\.[a-z]+$/i, ''))) return 'already';
      uploads = uploads.map((u) => u.input);
      const bytes = Uint8Array.from(atob(resume.data), (c) => c.charCodeAt(0));
      for (const input of uploads) {
        const transfer = new DataTransfer();
        transfer.items.add(new File([bytes], resume.name, { type: resume.type }));
        input.files = transfer.files;
        input.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
        input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      }
      return 'attached';
    }

    let profile = null;

    // An application form (it takes a resume) still counts as worth a panel with no written questions
    const isApplication = () => deepAll('input[type="file"]').length > 0;

    let host = null;
    let items = [];

    // Where the panel sits, its size, and whether it's collapsed: one setting for every
    // page, so it stays where you put it. Starts at the top right, 400px wide.
    const LAYOUT_KEY = 'panelLayout';
    function setUpLayout(panel) {
      const header = panel.querySelector('header');
      const place = (layout) => {
        const width = Math.min(layout.width || 400, innerWidth - 16);
        const left = Math.max(8, Math.min(layout.left ?? innerWidth - width - 12, innerWidth - width - 8));
        const top = Math.max(8, Math.min(layout.top ?? 12, innerHeight - 48));
        // Keep the bottom edge (and its resize corner) on screen
        const height = Math.max(120, Math.min(layout.height || innerHeight - 24, innerHeight - top - 8));
        Object.assign(panel.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
        panel.classList.toggle('collapsed', !!layout.collapsed);
      };
      let layout = {};
      let loaded = false;
      place(layout);
      if (alive()) chrome.storage.local.get(LAYOUT_KEY).then((saved) => { layout = saved[LAYOUT_KEY] || {}; place(layout); loaded = true; });
      const store = (changes) => {
        layout = { ...layout, ...changes };
        if (alive()) chrome.storage.local.set({ [LAYOUT_KEY]: layout });
      };

      header.addEventListener('pointerdown', (event) => {
        if (event.target.closest('button') || event.button !== 0) return;
        const startX = event.clientX - panel.offsetLeft;
        const startY = event.clientY - panel.offsetTop;
        header.setPointerCapture(event.pointerId);
        const move = (e) => {
          panel.style.left = `${Math.max(0, Math.min(e.clientX - startX, innerWidth - 60))}px`;
          panel.style.top = `${Math.max(0, Math.min(e.clientY - startY, innerHeight - 40))}px`;
        };
        const up = () => {
          header.removeEventListener('pointermove', move);
          store({ left: panel.offsetLeft, top: panel.offsetTop });
          place(layout);
        };
        header.addEventListener('pointermove', move);
        header.addEventListener('pointerup', up, { once: true });
      });

      // Resizing (the native corner handle) is saved once it settles
      let sizeTimer;
      new ResizeObserver(() => {
        if (!loaded || panel.classList.contains('collapsed')) return;
        clearTimeout(sizeTimer);
        sizeTimer = setTimeout(() => store({ width: panel.offsetWidth, height: panel.offsetHeight }), 300);
      }).observe(panel);

      panel.querySelector('.collapse').addEventListener('click', () => {
        store({ collapsed: !layout.collapsed });
        place(layout);
      });
    }

    const CSS_TEXT = `
      :host { all: initial; }
      .panel { position: fixed; box-sizing: border-box; min-width: 280px; min-height: 120px; resize: both; overflow: hidden;
        z-index: 2147483647; display: flex; flex-direction: column; font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #ffffff; color: #1f2328; border: 1px solid #d0d7de; border-radius: 10px; box-shadow: 0 8px 30px rgba(0,0,0,.18); }
      header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #d0d7de; cursor: move; user-select: none; }
      header b { flex: 1; font-size: 14px; }
      header button { cursor: pointer; }
      .panel.collapsed { height: auto !important; min-height: 0; resize: none; }
      .panel.collapsed > :not(header) { display: none; }
      .panel.collapsed header { border-bottom: none; }
      .actions { display: flex; gap: 6px; padding: 8px 12px; border-bottom: 1px solid #eaeef2; }
      .job { padding: 6px 12px; color: #59636e; font-size: 12px; border-bottom: 1px solid #eaeef2; }
      .list { flex: 1; overflow-y: auto; padding: 8px 12px 16px; }
      .q { border: 1px solid #d0d7de; border-radius: 8px; padding: 10px; margin-top: 10px; }
      .qhead { display: flex; align-items: flex-start; gap: 6px; }
      .label { flex: 1; font-weight: 600; cursor: pointer; }
      button.skip { padding: 0 6px; line-height: 20px; border: none; background: none; color: #59636e; }
      button.skip:hover { color: #cf222e; background: none; }
      button.link { padding: 0 0 0 6px; border: none; background: none; color: #0969da; text-decoration: underline; font-size: 12px; }
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
        .actions { border-color: #21262d; }
        button.skip, button.link, button.skip:hover { background: none; }
        button.skip { color: #9198a1; }
        button.link { color: #4493f8; }
        .limit, .count, .empty { color: #9198a1; }
        textarea, button { background: #21262d; border-color: #30363d; }
        textarea.answer { background: #0d1117; }
        button:hover { background: #30363d; }
      }`;

    // After a resume upload, sites like SmartRecruiters read it and fill fields
    // themselves, seconds later, which can overwrite Fill rest's answers. This waits up
    // to `limit` ms for the form to change, then for it to settle; true if it changed.
    const formSnapshot = () => deepAll(FIELDS).map((f) => (f.type === 'checkbox' || f.type === 'radio' ? f.checked : f.value)).join('\u0001') +
      deepAll('[role="combobox"], [aria-haspopup="listbox"]').map((el) => deepText(el).trim()).join('\u0001');
    async function formChangedBySite(limit) {
      const before = formSnapshot();
      const start = Date.now();
      while (Date.now() - start < limit) {
        await sleep(500);
        if (formSnapshot() === before) continue;
        let last = formSnapshot();
        for (let stable = 0; stable < 4 && Date.now() - start < limit + 10000; ) {
          await sleep(500);
          const now = formSnapshot();
          stable = now === last ? stable + 1 : 0;
          last = now;
        }
        return true;
      }
      return false;
    }

    // A plain-text sketch of a piece of the page (tags, roles, labels, text), shadow
    // roots included, so a field Fill rest gets wrong can be diagnosed from a paste
    function outline(node, depth = 0) {
      if (!node || depth > 7) return '';
      const attrs = ['id', 'role', 'type', 'name', 'aria-haspopup', 'aria-expanded', 'aria-label', 'placeholder', 'value']
        .map((a) => node.getAttribute?.(a) ? `${a}="${node.getAttribute(a).slice(0, 40)}"` : '').filter(Boolean).join(' ');
      const text = [...(node.childNodes || [])].filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent.trim()).join(' ').slice(0, 50);
      // A component shows its shadow children plus the light children it slots in
      const kids = [...(node.shadowRoot ? node.shadowRoot.children : []), ...(node.children || [])];
      return `${'  '.repeat(depth)}<${node.localName}${attrs ? ` ${attrs}` : ''}${node.shadowRoot ? ' #shadow' : ''}>${text ? ` ${text}` : ''}\n` +
        kids.filter((k) => !/^(script|style|svg|path|slot|head)$/.test(k.localName) && k.id !== 'jobtracker-answers')
          .slice(0, 20).map((k) => outline(k, depth + 1)).join('');
    }

    let report = '';
    function setReport(lines) {
      // The phone box's surroundings: the part of these forms most likely to differ
      // Climb to the phone box's whole row (where a country picker would sit), not the page
      const phones = deepAll('input[type="tel"]').map((tel) => {
        let box = up(tel);
        for (let i = 0; up(box) && i < 5 && fieldsIn(up(box)).length <= 4; i++) box = up(box);
        return `--- around the phone box ---\n${outline(box).split('\n').slice(0, 120).join('\n')}`;
      });
      // Every field on the page, so it's clear what was (and wasn't) there to fill
      const fields = deepAll(FIELDS).filter((f) => f.type !== 'hidden' && shown(f)).map((f) =>
        `  ${f.localName}${f.type ? `[${f.type}]` : ''} ${JSON.stringify(labelFor(f).slice(0, 60))} = ${JSON.stringify(
          (f.type === 'checkbox' || f.type === 'radio' ? String(f.checked) : f.localName === 'select' ? f.selectedOptions[0]?.text || '' : f.value).slice(0, 40))}`);
      // The education section as shown (summary cards and their edit buttons), so editing
      // entries can be automated for forms that only show the dates after "Edit"
      const heading = deepAll('h1, h2, h3, h4, legend, [role="heading"], spl-typography-heading, p, span')
        .find((el) => /^education$/i.test(clean(deepText(el))));
      let section = heading && up(heading);
      for (let i = 0; section && i < 3 && clean(deepText(section)).length < 60; i++) section = up(section);
      const education = section ? [`--- education section ---\n${outline(section).split('\n').slice(0, 100).join('\n')}`] : ['--- no education section found ---'];
      report = [`JobTracker Fill rest report: ${location.host}${location.pathname}`, ...lines, '--- every field on the page ---', ...fields, ...phones, ...education].join('\n');
    }

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

    // Notes and drafts are saved per page and question, so Rescan or reloading the
    // page or the extension doesn't lose them (kept for 30 days)
    const SAVE_KEY = 'answers';
    const keyFor = (item) => `${location.host}${location.pathname}|${item.label}`;
    let saveTimer;
    function save() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        if (!alive()) return;
        const { [SAVE_KEY]: saved = {} } = await chrome.storage.local.get(SAVE_KEY);
        const cutoff = Date.now() - 30 * 24 * 3600 * 1000;
        for (const key of Object.keys(saved)) if (saved[key].t < cutoff) delete saved[key];
        for (const item of items) {
          const note = item.note.value;
          const answer = item.answer.value;
          if (note || answer || item.hidden) saved[keyFor(item)] = { note, answer, hidden: item.hidden, t: Date.now() };
          else delete saved[keyFor(item)];
        }
        await chrome.storage.local.set({ [SAVE_KEY]: saved });
      }, 300);
    }

    // An answer you fill in or copy counts as approved: the server remembers it so
    // later drafts for similar questions reuse the same story
    function remember(item) {
      if (!item.answer.value.trim()) return;
      send({
        type: 'save-answer', frameUrl: location.href,
        question: item.label, note: item.note.value.trim(), answer: item.answer.value,
      });
    }

    // A skipped question is left out of Draft all and Fill all, and stays skipped on this page
    function setHidden(item, hidden, persist = true) {
      item.hidden = hidden;
      item.box.style.display = hidden ? 'none' : '';
      updateSummary();
      if (persist) save();
    }

    function updateSummary() {
      const root = host.shadowRoot;
      const shown = items.filter((item) => !item.hidden).length;
      const skipped = items.length - shown;
      root.querySelector('.summary').textContent =
        `${shown} open-ended question${shown === 1 ? '' : 's'} on this page` + (skipped ? ` · ${skipped} skipped` : '');
      root.querySelector('.show-hidden').style.display = skipped ? '' : 'none';
      root.querySelector('.all').disabled = !shown;
      root.querySelector('.fill-all').disabled = !shown;
    }

    // One round of filling: a few passes over the blanks (answering one question can
    // reveal another, like race after Hispanic/Latino), then education-date corrections
    async function fillPasses() {
      // Search boxes and custom dropdowns go last, since an open one blocks typing elsewhere
      let filled = 0;
      const tried = new Set();
      const left = new Map();
      const lines = [];
      for (let pass = 0; pass < 3; pass++) {
        const blanks = findBlanks().filter((b) => !tried.has(`${b.kind}|${b.label}`));
        if (!blanks.length) break;
        const late = (b) => (b.kind === 'search' || b.kind === 'dropdown' ? 1 : 0);
        blanks.sort((a, b) => late(a) - late(b));
        for (const blank of blanks) {
          tried.add(`${blank.kind}|${blank.label}`);
          const value = answerFor(blank, profile);
          const done = value && (blank.kind === 'search' ? await fillSearch(blank, value)
            : blank.kind === 'dropdown' ? await fillDropdown(blank, value) : blank.apply(value));
          if (done) filled++;
          else if (blank.required) left.set(`${blank.kind}|${blank.label}`, blank);
          lines.push(`${done ? 'filled' : 'left  '} [${blank.kind}${blank.required ? ', required' : ''}] ${blank.label.slice(0, 80)} => ${JSON.stringify(value || '')}`);
        }
        await sleep(500);
      }
      // Education dates someone else filled (Simplify reads them off the resume, often
      // a month off) are corrected to the profile's
      for (const field of deepAll('input[type="text"], input[type="month"], input[type="date"], input:not([type])')) {
        if (!field.value || !shown(field)) continue;
        const blank = { kind: 'text', label: labelFor(field), options: [], target: field, field };
        if (!/\b(from|to|start|end|begin|until|finish|graduat\w*|completion)\b/i.test(blank.label)) continue;
        const expected = educationDate(blank, profile);
        if (expected && field.value !== expected && !(field.type === 'month' && !/^\d{4}-\d{2}$/.test(expected))) {
          lines.push(`fixed  [education date] ${blank.label} ${JSON.stringify(field.value)} => ${JSON.stringify(expected)}`);
          fill(field, expected);
          filled++;
        }
      }
      return { filled, left, lines };
    }

    async function fillRest() {
      for (const el of deepAll('[data-jt-left]')) {
        el.style.outline = '';
        el.removeAttribute('data-jt-left');
      }
      const buttons = host.shadowRoot.querySelectorAll('button');
      buttons.forEach((b) => { b.disabled = true; });
      setStatus('Filling the form…');
      try {
        if (!profile) {
          const result = await new Promise((resolve) => send({ type: 'get-profile' }, resolve));
          if (!result || result.error) throw new Error(result?.error || 'No response. Is the JobTracker server running?');
          profile = result.profile;
        }
        const resume = await attachResume();
        // Sites that read the resume (Ashby, SmartRecruiters) rebuild or rewrite fields,
        // at once or seconds later. So: let the first wave settle, fill, watch for a later
        // rewrite, then always make one last pass (it only touches blank or wrong fields).
        if (resume === 'attached') {
          setStatus('Attached your resume; letting the site read it…');
          await sleep(1500);
          await formChangedBySite(1000);
        }
        let { filled, left, lines } = await fillPasses();
        if (resume === 'attached') {
          setStatus(`Filled ${filled} field${filled === 1 ? '' : 's'}; checking whether the site rewrites them from your resume…`);
          if (await formChangedBySite(10000)) lines.push('site changed the form after the resume upload');
          const again = await fillPasses();
          if (again.filled) lines.push(`last pass filled or fixed ${again.filled} more:`, ...again.lines.filter((l) => !l.startsWith('left')));
          filled += again.filled;
          left = again.left;
        }
        for (const blank of left.values()) {
          blank.target.style.outline = '2px solid #f0883e';
          blank.target.style.outlineOffset = '2px';
          blank.target.setAttribute('data-jt-left', '');
        }
        const resumeNote = { attached: 'Attached your resume. ', already: 'Resume already attached. ', none: 'No resume upload found on this page. ' }[resume];
        setStatus(`${resumeNote}Filled ${filled} field${filled === 1 ? '' : 's'}.` +
          (left.size ? ` ${left.size} required left for you, outlined in orange.` : ' Check the form, then draft the written answers.'));
        setReport([`resume: ${resume}`, ...lines]);
        // If something came out wrong, this report shows what Fill rest saw and did
        const copy = document.createElement('button');
        copy.className = 'link';
        copy.textContent = 'Copy report';
        copy.title = 'Copy what Fill rest found and did on this page, to paste when something is wrong';
        copy.addEventListener('click', async () => {
          await navigator.clipboard.writeText(report);
          copy.textContent = 'Copied';
        });
        host.shadowRoot.querySelector('.status').appendChild(copy);
      } catch (e) {
        setStatus(String(e.message || e), true);
      } finally {
        buttons.forEach((b) => { b.disabled = false; });
        updateSummary();
      }
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
      send({
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
        save();
        if (result.job) host.shadowRoot.querySelector('.matched').textContent = ` · ${result.job}`;
        setStatus('Review each answer and fix any detail that isn\'t right, then Copy or Fill.');
      });
    }

    function render() {
      // What's typed in the panel right now carries over a Rescan, even before it's saved
      const typed = new Map(items.map((item) => [item.label, { note: item.note.value, answer: item.answer.value, hidden: item.hidden }]));
      items = findQuestions().map((q) => ({ ...q, redo: false, hidden: false }));
      if (!host) {
        document.getElementById('jobtracker-answers')?.remove(); // left by an older copy of the extension
        host = document.createElement('div');
        host.id = 'jobtracker-answers';
        host.attachShadow({ mode: 'open' });
        document.documentElement.appendChild(host);
      }
      const root = host.shadowRoot;
      root.innerHTML = `<style>${CSS_TEXT}</style>
        <div class="panel" role="dialog" aria-label="JobTracker answers">
          <header title="Drag to move; resize from the bottom-right corner"><b>Application answers</b>
            <button class="collapse" aria-label="Collapse" title="Collapse to this bar (click again to expand)">–</button>
            <button class="pause" title="Stop opening this panel by itself on job pages (click the toolbar icon to turn it back on)">Pause</button>
            <button class="close" aria-label="Close" title="Hide on this page">✕</button></header>
          <div class="actions">
            <button class="fill-rest" title="Attach your resume and fill the rest of the form (dropdowns, yes/no questions, checkboxes, short fields) from your standard answers. Free: no AI calls.">Fill rest</button>
            <button class="primary all">Draft all</button>
            <button class="fill-all" title="Put every drafted answer into its form field">Fill all</button>
            <button class="rescan" title="Look for questions again (e.g. after moving to the next page of the form)">Rescan</button>
          </div>
          <div class="job"><span class="summary"></span><button class="link show-hidden">show</button><span class="matched"></span></div>
          <div class="list"></div>
          <div class="status">Add a note to steer any answer (e.g. "say it was my Chimagine app"), then Draft all.</div>
        </div>`;
      const list = root.querySelector('.list');
      if (!items.length) {
        list.innerHTML = '<div class="empty">No written questions here. Use Fill rest for the rest of the form, and if the form has more pages, go to the next one.</div>';
      }
      for (const item of items) {
        const box = document.createElement('div');
        box.className = 'q';
        const label = document.createElement('div');
        label.className = 'label';
        label.textContent = item.label;
        label.title = 'Scroll to this question';
        label.addEventListener('click', () => item.field.scrollIntoView({ behavior: 'smooth', block: 'center' }));
        const skip = document.createElement('button');
        skip.className = 'skip';
        skip.textContent = '✕';
        skip.title = "Skip this question (Draft all and Fill all leave it out)";
        skip.setAttribute('aria-label', 'Skip this question');
        skip.addEventListener('click', () => setHidden(item, true));
        const head = document.createElement('div');
        head.className = 'qhead';
        head.append(label, skip);
        box.appendChild(head);
        item.box = box;
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
        item.note.addEventListener('input', save);
        item.answer.addEventListener('input', () => { updateCount(item); save(); });
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
          remember(item);
          copy.textContent = 'Copied';
          setTimeout(() => { copy.textContent = 'Copy'; }, 1200);
        });
        const fillButton = document.createElement('button');
        fillButton.textContent = 'Fill';
        fillButton.title = 'Put this answer into the form field';
        fillButton.addEventListener('click', () => {
          fill(item.field, item.answer.value);
          remember(item);
          item.field.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        row.append(item.count, redo, copy, fillButton);
        box.append(item.note, item.answer, row);
        list.appendChild(box);
        updateCount(item);
      }
      if (alive()) chrome.storage.local.get(SAVE_KEY).then(({ [SAVE_KEY]: saved = {} }) => {
        for (const item of items) {
          const previous = typed.get(item.label) || saved[keyFor(item)];
          if (!previous) continue;
          if (previous.hidden) setHidden(item, true, false);
          if (item.note.value || item.answer.value) continue;
          item.note.value = previous.note || '';
          item.answer.value = previous.answer || '';
          updateCount(item);
        }
      });
      root.querySelector('.show-hidden').addEventListener('click', () => {
        items.filter((item) => item.hidden).forEach((item) => setHidden(item, false));
      });
      updateSummary();
      setUpLayout(root.querySelector('.panel'));
      root.querySelector('.close').addEventListener('click', () => {
        close();
        send({ type: 'panel-closed' });
      });
      root.querySelector('.pause').addEventListener('click', () => {
        close();
        send({ type: 'auto-open-off' });
      });
      startWatching();
      root.querySelector('.rescan').addEventListener('click', render);
      root.querySelector('.fill-rest').addEventListener('click', fillRest);
      const all = root.querySelector('.all');
      all.addEventListener('click', () => draft(items.filter((item) => !item.hidden)));
      const fillAll = root.querySelector('.fill-all');
      fillAll.addEventListener('click', () => {
        const ready = items.filter((item) => !item.hidden && item.answer.value.trim());
        ready.forEach((item) => { fill(item.field, item.answer.value); remember(item); });
        setStatus(ready.length ? `Filled ${ready.length} answer${ready.length === 1 ? '' : 's'} into the form.` : 'Nothing to fill yet; draft the answers first.');
      });
    }

    let observer = null;
    let watchTimer;
    const questionsChanged = () => {
      const now = findQuestions();
      return now.length !== items.length || now.some((q, i) => q.field !== items[i].field);
    };
    // Forms that move to their next step without a page load (like Workday) get
    // rescanned; a page still waiting for its questions opens the panel when they appear
    function startWatching() {
      if (observer) return;
      observer = new MutationObserver(() => {
        if (!alive()) {
          observer?.disconnect();
          observer = null;
          return;
        }
        clearTimeout(watchTimer);
        watchTimer = setTimeout(() => {
          if (host ? questionsChanged() : count()) render();
        }, 800);
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
    function close() {
      observer?.disconnect();
      observer = null;
      host?.remove();
      host = null;
    }

    const count = () => findQuestions().length || (isApplication() ? 1 : 0);
    window.__jobtrackerAnswers = {
      count,
      // Called on every page load in a tab with the panel open; leaves an up-to-date panel alone
      open: () => { if (!host || questionsChanged()) render(); },
      watch: () => { if (!host) startWatching(); },
    };
  }
  return window.__jobtrackerAnswers.count();
})();
