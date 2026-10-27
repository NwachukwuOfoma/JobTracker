// Runs in the page's own JavaScript world (injected with the answer panel), because
// React dropdowns like Greenhouse's ignore simulated clicks and keys. Through the
// component itself it reports a dropdown's options and selects one. The panel asks
// via a DOM event carrying JSON, since the two worlds share only the DOM.
(() => {
  if (window.__jobtrackerSelect) return;
  window.__jobtrackerSelect = true;

  const optionLabel = (o) => (o && typeof o === 'object' ? String(o.label ?? o.value ?? '') : String(o));

  // The react-select component that owns this element, found by walking up React's tree
  function selectFor(el) {
    const key = Object.keys(el).find((k) => k.startsWith('__reactFiber'));
    for (let fiber = key && el[key]; fiber; fiber = fiber.return) {
      const node = fiber.stateNode;
      if (node && typeof node.selectOption === 'function' && node.props) return node;
    }
    return null;
  }
  const options = (select) => (select.props.options || []).flatMap((o) => (o && o.options) || [o]);

  document.addEventListener('jobtracker-select', (event) => {
    const { action, id, value } = JSON.parse(event.detail);
    const el = document.querySelector(`[data-jt-id="${id}"]`);
    const select = el && selectFor(el);
    let result = null;
    if (select && action === 'state') {
      const current = select.props.value;
      const empty = current == null || current === '' || (Array.isArray(current) && !current.length);
      result = { options: options(select).map(optionLabel), empty };
    } else if (select && action === 'search') {
      // Searchable dropdowns (a location) load their options from what's typed
      select.props.onInputChange?.(value, { action: 'input-change', prevInputValue: '' });
      select.props.onMenuOpen?.();
      result = true;
    } else if (select && action === 'choose') {
      const option = options(select).find((o) => optionLabel(o) === value);
      if (option) {
        select.selectOption(option);
        result = true;
      }
    } else if (select && action === 'close') {
      // An open search menu swallows typing in the form's other fields
      select.props.onInputChange?.('', { action: 'menu-close', prevInputValue: '' });
      select.props.onMenuClose?.();
      select.blurInput?.();
      result = true;
    }
    document.dispatchEvent(new CustomEvent('jobtracker-select-result', { detail: JSON.stringify({ id, result }) }));
  });
})();
