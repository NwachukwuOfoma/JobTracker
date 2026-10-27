// Injected only when you click the JobTracker toolbar icon on an application page
// (into every frame, since forms like Greenhouse's are often embedded). Finds the
// open-ended questions, then drafts answers you review, edit and paste or fill in.
(() => {
  if (!window.__jobtrackerAnswers) {
    // Fields that are form data, not questions to write an answer for
    const SKIP = /\b(first|last|middle|full|legal|preferred)?\s*name\b|e-?mail|phone|mobile|linked\s?in|github|twitter|website|portfolio|\burl\b|address|city|state|zip|postal|country|location|salary|compensation|pronoun|school|university|degree|major|gpa|graduation|date|referr|how did you hear|resume|\bcv\b|cover letter|signature|initials/i;
    const OPEN_ENDED = /\?|\b(why|describe|explain|tell us|share|what|how|which|briefly|walk us)\b/i;
    // Short questions that want a number ("How many years of experience do you have?")
    const NUMERIC = /^(how many|number of)\b|\byears of (\S+ )?(work |professional |industry )?experience do you have\b/i;

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
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.dispatchEvent(new Event('change', { bubbles: true }));
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
      !!(el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.getClientRects().length) ||
      !!el.closest('label')?.getClientRects().length);

    function optionText(input) {
      const label = (input.id && document.querySelector(`label[for="${CSS.escape(input.id)}"]`)) || input.closest('label');
      return clean(label?.innerText || input.getAttribute('aria-label') || input.value || input.textContent);
    }

    // One question's block on the page (Ashby's fieldEntry, a fieldset, a role=group)
    const ENTRY = 'fieldset, [role="radiogroup"], [role="group"], [class*="fieldEntry" i], [class*="field-entry" i]';

    // The question above a group of options: its legend, its ARIA label, or the text
    // of the nearest container holding the whole group, minus the options' own labels
    function groupLabel(inputs) {
      const legend = inputs[0].closest('fieldset')?.querySelector('legend');
      if (legend && clean(legend.innerText)) return clean(legend.innerText);
      const group = inputs[0].closest('[role="radiogroup"], [role="group"]');
      const labelledBy = group?.getAttribute('aria-labelledby');
      if (labelledBy) {
        const text = clean(labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' '));
        if (text) return text;
      }
      if (clean(group?.getAttribute('aria-label'))) return clean(group.getAttribute('aria-label'));
      const optionTexts = inputs.map(optionText).filter(Boolean);
      let node = inputs[0].parentElement;
      for (let depth = 0; node && depth < 8; depth++, node = node.parentElement) {
        if (!inputs.every((i) => node.contains(i))) continue;
        let text = node.innerText || '';
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
        const label = field.id && document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
        if (label && /[*✱]/.test(label.innerText)) return true;
      }
      return /[*✱]|required/i.test((target.closest(ENTRY) || target.parentElement)?.innerText.slice(0, 400) || '');
    }

    function findBlanks() {
      const written = new Set(findQuestions().map((q) => q.field));
      const blanks = [];
      const add = (blank) => { if (blank.label) blanks.push({ ...blank, required: isRequired(blank) }); };

      // Yes/No button pairs (Ashby): unanswered while neither is pressed
      const pairs = new Map();
      for (const button of document.querySelectorAll('button')) {
        if (!/^(yes|no)$/i.test(clean(button.textContent)) || !shown(button)) continue;
        if (!pairs.has(button.parentElement)) pairs.set(button.parentElement, []);
        pairs.get(button.parentElement).push(button);
      }
      const pairEntries = [];
      for (const [parent, buttons] of pairs) {
        if (buttons.length < 2) continue;
        pairEntries.push(parent.closest(ENTRY) || parent.parentElement);
        if (buttons.some((b) => b.getAttribute('aria-pressed') === 'true' || /active|selected/i.test(b.className))) continue;
        add({
          kind: 'choice', label: groupLabel(buttons), options: buttons.map((b) => clean(b.textContent)), target: parent,
          apply: (value) => { const b = buttons.find((x) => clean(x.textContent) === value); b?.click(); return !!b; },
        });
      }

      for (const select of document.querySelectorAll('select')) {
        if (select.disabled || !shown(select)) continue;
        const options = [...select.options].filter((o) => o.value !== '' && !/^\s*(select|choose|--|please)/i.test(o.text));
        if (!options.length || options.includes(select.selectedOptions[0])) continue;
        add({
          kind: 'choice', label: labelFor(select), options: options.map((o) => clean(o.text)), target: select,
          apply: (value) => {
            const option = options.find((o) => clean(o.text) === value);
            if (!option) return false;
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, option.value);
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
          },
        });
      }

      // Radio and checkbox groups, grouped by the question block they sit in (some forms
      // reuse one name across several questions)
      const groups = new Map();
      for (const input of document.querySelectorAll('input[type="radio"], input[type="checkbox"]')) {
        if (input.disabled || !shown(input) || pairEntries.some((entry) => entry?.contains(input))) continue;
        const key = input.closest(ENTRY) || (input.name ? `${input.type}:${input.name}` : input);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(input);
      }
      for (const inputs of groups.values()) {
        if (inputs.some((i) => i.checked)) continue;
        const target = inputs[0].closest(ENTRY) || inputs[0].parentElement;
        if (inputs.length === 1 && inputs[0].type === 'checkbox') {
          const box = inputs[0];
          add({
            kind: 'checkbox', label: clean(`${groupLabel(inputs)} ${optionText(box)}`), options: ['checked', 'unchecked'], target, inputs,
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
      for (const input of document.querySelectorAll('input[role="combobox"]')) {
        if (!shown(input)) continue;
        const state = pageSelect('state', input);
        const target = input.closest('[class*="control"]') || input;
        if (state && !state.empty) continue;
        if (!state && input.value) continue;
        if (state && state.options.length) {
          add({ kind: 'choice', label: labelFor(input), options: state.options, target, apply: (value) => !!pageSelect('choose', input, value) });
        } else if (/location|city|where (are you|do you live)|school|university|college|degree/i.test(labelFor(input))) {
          add({ kind: 'search', label: labelFor(input), options: [], target, input, react: !!state });
        }
      }

      const textFields = 'input[type="text"], input[type="email"], input[type="url"], input[type="tel"], input[type="number"], input[type="date"], input:not([type])';
      for (const field of document.querySelectorAll(textFields)) {
        if (written.has(field) || field.value || field.disabled || field.readOnly || !shown(field)) continue;
        if (field.getAttribute('role') === 'combobox' || field.hasAttribute('aria-autocomplete') || field.getAttribute('aria-hidden') === 'true') continue;
        const label = labelFor(field);
        if (label.length < 3) continue;
        add({
          kind: 'text', label, options: [], target: field, field,
          apply: (value) => {
            // A date box only takes YYYY-MM-DD; "Immediately" can't go in one
            if (field.type === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
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

    function rules(P) {
      const worksHere = () => (P.past_employers || []).some((e) => new RegExp(`\\b${escapeRe(e)}\\b`, 'i').test(`${document.title} ${location.hostname}`));
      const text = (value) => (b) => (b.kind === 'text' || b.kind === 'search' ? value : '');
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
        [/enrolled|graduat|currently a student/, (b) => pick(b.options, [/already graduated|^graduated|not (currently )?(enrolled|a student)|alumn/i])],
        [/start date|start working|available to start|earliest|notice period/, (b) => (b.kind === 'text' ? P.start_date
          : pick(b.options, [/immediate|asap|right away|^now/i, /2 weeks|two weeks/i]))],
        [/salary|compensation|pay (expectation|range|requirement)|desired pay|expected pay/, (b) => (b.kind === 'text'
          ? (b.field?.type === 'number' || /number|numeric|annual|usd|\$|amount/i.test(b.label) ? P.salary_number : P.salary_text)
          : rangeOption(b.options, Number(P.salary_number)))],
        [/acknowledg|consent|agree|certif|attest|confirm|privacy|terms|accurate|read and understand/, Y],
        // Contact and background details
        [/preferred (first )?name|first name|given name/, text(P.first_name)],
        [/last name|surname|family name/, text(P.last_name)],
        [/full name|legal name|^name\b|your name/, text(`${P.first_name} ${P.last_name}`)],
        [/e-?mail/, text(P.email)],
        [/phone|mobile|cell/, text(P.phone)],
        [/linkedin/, text(P.linkedin)],
        [/github/, text(P.github)],
        [/website|portfolio|personal (site|url)/, text(P.website)],
        [/\bcountry\b/, (b) => (b.kind === 'text' ? P.country : pick(b.options, [/^united states|^usa?$|^u\.s\./i]))],
        [/\b(state|province)\b/, (b) => (b.kind === 'text' ? P.state : pick(b.options, [new RegExp(`^${escapeRe(P.state)}`, 'i'), /^il$/i]))],
        [/\bcity\b|location|located|where (are you|do you live)|current address|based in/, (b) => (b.kind === 'text' || b.kind === 'search'
          ? (b.kind === 'search' || /\bcity\b/i.test(b.label) ? P.city : P.location) : '')],
        [/school|university|college|institution/, (b) => (b.kind === 'choice' ? pick(b.options, [/johns hopkins/i]) : P.school)],
        [/degree/, (b) => (b.kind === 'text' ? P.degree : b.kind === 'search' ? 'Master' : pick(b.options, [/master/i]))],
      ];
    }

    function answerFor(blank, P) {
      // "United States" would otherwise trip the state rule
      const question = blank.label.toLowerCase().replace(/united states/g, 'usa');
      for (const [pattern, decide] of rules(P)) if (pattern.test(question)) return decide(blank) || '';
      return '';
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
      const options = [...document.querySelectorAll('[role="option"]')].filter((o) => o.getClientRects().length);
      const text = pick(options.map((o) => clean(o.textContent)), prefer);
      const option = options.find((o) => clean(o.textContent) === text);
      option?.click();
      return !!option;
    }

    // Attaches your newest resume to empty resume uploads (never cover letters)
    async function attachResume() {
      const uploads = [...document.querySelectorAll('input[type="file"]')].filter((input) => {
        const context = `${input.name} ${input.id} ${labelFor(input)} ${(input.closest(ENTRY) || input.parentElement)?.innerText.slice(0, 120) || ''}`;
        return !input.files.length && /resume|\bcv\b/i.test(context) && !/cover/i.test(context);
      });
      if (!uploads.length) return 0;
      const resume = await new Promise((resolve) => chrome.runtime.sendMessage({ type: 'get-resume' }, resolve));
      if (!resume || resume.error) return 0;
      const bytes = Uint8Array.from(atob(resume.data), (c) => c.charCodeAt(0));
      for (const input of uploads) {
        const transfer = new DataTransfer();
        transfer.items.add(new File([bytes], resume.name, { type: resume.type }));
        input.files = transfer.files;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return uploads.length;
    }

    let profile = null;

    // An application form (it takes a resume) still counts as worth a panel with no written questions
    const isApplication = () => !!document.querySelector('input[type="file"]');

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
      chrome.storage.local.get(LAYOUT_KEY).then((saved) => { layout = saved[LAYOUT_KEY] || {}; place(layout); loaded = true; });
      const store = (changes) => {
        layout = { ...layout, ...changes };
        chrome.storage.local.set({ [LAYOUT_KEY]: layout });
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
      chrome.runtime.sendMessage({
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

    async function fillRest() {
      for (const el of document.querySelectorAll('[data-jt-left]')) {
        el.style.outline = '';
        el.removeAttribute('data-jt-left');
      }
      const buttons = host.shadowRoot.querySelectorAll('button');
      buttons.forEach((b) => { b.disabled = true; });
      setStatus('Filling the form…');
      try {
        if (!profile) {
          const result = await new Promise((resolve) => chrome.runtime.sendMessage({ type: 'get-profile' }, resolve));
          if (!result || result.error) throw new Error(result?.error || 'No response. Is the JobTracker server running?');
          profile = result.profile;
        }
        const attached = await attachResume();
        if (attached) await sleep(1500); // some forms read the resume and fill fields from it
        // A few passes: answering one question can reveal another (race appears after
        // Hispanic/Latino). Search boxes go last, since an open one blocks typing elsewhere.
        let filled = 0;
        const tried = new Set();
        const left = new Map();
        for (let pass = 0; pass < 3; pass++) {
          const blanks = findBlanks().filter((b) => !tried.has(`${b.kind}|${b.label}`));
          if (!blanks.length) break;
          blanks.sort((a, b) => (a.kind === 'search') - (b.kind === 'search'));
          for (const blank of blanks) {
            tried.add(`${blank.kind}|${blank.label}`);
            const value = answerFor(blank, profile);
            const done = value && (blank.kind === 'search' ? await fillSearch(blank, value) : blank.apply(value));
            if (done) filled++;
            else if (blank.required) left.set(`${blank.kind}|${blank.label}`, blank);
          }
          await sleep(500);
        }
        for (const blank of left.values()) {
          blank.target.style.outline = '2px solid #f0883e';
          blank.target.style.outlineOffset = '2px';
          blank.target.setAttribute('data-jt-left', '');
        }
        setStatus(`${attached ? 'Attached your resume. ' : ''}Filled ${filled} field${filled === 1 ? '' : 's'}.` +
          (left.size ? ` ${left.size} required left for you, outlined in orange.` : ' Check the form, then draft the written answers.'));
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
      chrome.storage.local.get(SAVE_KEY).then(({ [SAVE_KEY]: saved = {} }) => {
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
        chrome.runtime.sendMessage({ type: 'panel-closed' });
      });
      root.querySelector('.pause').addEventListener('click', () => {
        close();
        chrome.runtime.sendMessage({ type: 'auto-open-off' });
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
