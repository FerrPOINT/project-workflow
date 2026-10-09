(() => {
  const preference = window.SdlcThemePreference;
  if (preference) {
    const legacyKey = document.documentElement.dataset.themeStorageKey || 'theme';
    const apply = () => {
      const theme = preference.read(legacyKey);
      document.documentElement.dataset.theme = theme;
      for (const option of document.querySelectorAll('[data-base-theme-option]')) option.checked = option.value === theme;
    };
    for (const option of document.querySelectorAll('[data-base-theme-option]')) option.addEventListener('change', () => { preference.set(option.value, legacyKey); apply(); });
    apply();
    preference.subscribe(apply);
  }
  for (const account of document.querySelectorAll('.base-ssr-account')) {
    const toggle = account.querySelector('summary');
    function closeAccount(restoreFocus) { account.open = false; if (restoreFocus) toggle?.focus(); }
    account.addEventListener('keydown', (event) => { if (event.key === 'Escape' && account.open) { event.preventDefault(); closeAccount(true); } });
    document.addEventListener('click', (event) => { if (event.target instanceof Node && !account.contains(event.target)) closeAccount(false); });
    account.addEventListener('focusout', (event) => { if (event.relatedTarget instanceof Node && !account.contains(event.relatedTarget)) closeAccount(false); });
  }
  const trigger = document.querySelector('[data-base-drawer-trigger]');
  const drawer = document.querySelector('[data-base-drawer]');
  if (!trigger || !drawer) return;
  const focusable = () => [...drawer.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]')].filter((item) => !item.disabled && item.getClientRects().length);
  function close() { drawer.close(); trigger.setAttribute('aria-expanded', 'false'); const target = trigger.getClientRects().length ? trigger : document.querySelector('main[tabindex="-1"]'); target?.focus(); }
  trigger.addEventListener('click', () => { drawer.showModal(); trigger.setAttribute('aria-expanded', 'true'); focusable()[0]?.focus(); });
  drawer.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
  drawer.addEventListener('click', (event) => { if (event.target instanceof Element && event.target.closest('[data-base-drawer-close],a[href]')) close(); });
  drawer.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (!items.length) { event.preventDefault(); return; }
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
  });
  window.matchMedia('(min-width: 768px)').addEventListener('change', (event) => { if (event.matches && drawer.open) close(); });
})();
