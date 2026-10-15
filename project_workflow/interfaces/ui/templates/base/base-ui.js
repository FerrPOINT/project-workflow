(() => {
  const preference = window.PdlcThemePreference || window.SdlcThemePreference;
  if (preference) {
    const legacyKey = document.documentElement.dataset.themeStorageKey || 'theme';
    const apply = () => {
      const theme = preference.read(legacyKey);
      document.documentElement.dataset.theme = theme;
      for (const option of /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('[data-base-theme-option]'))) option.checked = option.value === theme;
    };
    for (const option of /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('[data-base-theme-option]'))) option.addEventListener('change', () => { preference.set(/** @type {import("../src/lib/theme-preference.js").Theme} */ (option.value), legacyKey); apply(); });
    apply();
    preference.subscribe(apply);
  }
  for (const account of /** @type {NodeListOf<HTMLDetailsElement>} */ (document.querySelectorAll('.base-ssr-account'))) {
    const toggle = account.querySelector('summary');
    let pointerInAccount = false;
    function closeAccount(restoreFocus) { account.open = false; if (restoreFocus) toggle?.focus(); }
    // WebKit focuses an ancestor main before clicking a non-focusable link.
    // Keep the pressed menu item mounted until its click can be delivered.
    document.addEventListener('pointerdown', (event) => { pointerInAccount = event.target instanceof Node && account.contains(event.target); });
    document.addEventListener('pointerup', () => { pointerInAccount = false; });
    document.addEventListener('pointercancel', () => { pointerInAccount = false; });
    account.addEventListener('keydown', (event) => { if (event.key === 'Escape' && account.open) { event.preventDefault(); closeAccount(true); } });
    document.addEventListener('click', (event) => { if (event.target instanceof Node && !account.contains(event.target)) closeAccount(false); });
    account.addEventListener('focusout', (event) => { if (!pointerInAccount && event.relatedTarget instanceof Node && !account.contains(event.relatedTarget)) closeAccount(false); });
  }
  const trigger = /** @type {HTMLElement} */ (document.querySelector('[data-base-drawer-trigger]'));
  const drawer = /** @type {HTMLDialogElement} */ (document.querySelector('[data-base-drawer]'));
  if (!trigger || !drawer) return;
  const focusable = () => /** @type {HTMLElement[]} */ ([...drawer.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]')]).filter((item) => !/** @type {HTMLButtonElement} */ (item).disabled && item.getClientRects().length);
  function close() { drawer.close(); trigger.setAttribute('aria-expanded', 'false'); const target = trigger.getClientRects().length ? trigger : /** @type {HTMLElement} */ (document.querySelector('main[tabindex="-1"]')); target?.focus(); }
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

(() => {
function requestConfirmation(options){
  var dialog = document.getElementById('confirmDialog');
  var cancel = document.getElementById('confirmDialogCancel');
  var accept = document.getElementById('confirmDialogAccept');
  var trigger = /** @type {HTMLElement} */ (document.activeElement);
  var background = Array.from(/** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('[data-base-dialog-background]')));
  var previousInert = background.map(function(element){ return element.inert; });
  document.getElementById('confirmDialogEyebrow').textContent = options.eyebrow || 'Подтверждение';
  document.getElementById('confirmDialogTitle').textContent = options.title || 'Подтвердите действие';
  document.getElementById('confirmDialogCopy').textContent = options.message || '';
  accept.textContent = options.confirmLabel || 'Подтвердить';
  dialog.hidden = false;
  dialog.setAttribute('aria-hidden', 'false');
  background.forEach(function(element){ element.inert = true; });
  cancel.focus();
  return new Promise(function(resolve){
    function close(value){
      dialog.hidden = true;
      dialog.setAttribute('aria-hidden', 'true');
      background.forEach(function(element,index){ element.inert = previousInert[index]; });
      document.dispatchEvent(new Event('base-dialog-closed'));
      cancel.removeEventListener('click', onCancel);
      accept.removeEventListener('click', onAccept);
      dialog.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKeyDown);
      if(trigger && typeof trigger.focus === 'function'){ trigger.focus(); }
      resolve(value);
    }
    function onCancel(){ close(false); }
    function onAccept(){ close(true); }
    function onBackdrop(event){ if(event.target === dialog){ close(false); } }
    function onKeyDown(event){
      if(event.key === 'Escape'){ close(false); }
      if(event.key === 'Tab'){
        if(event.shiftKey && (document.activeElement === cancel || !dialog.contains(document.activeElement))){
          event.preventDefault();
          accept.focus();
        }else if(!event.shiftKey && (document.activeElement === accept || !dialog.contains(document.activeElement))){
          event.preventDefault();
          cancel.focus();
        }
      }
    }
    cancel.addEventListener('click', onCancel);
    accept.addEventListener('click', onAccept);
    dialog.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKeyDown);
  });
}
  window.PdlcBaseUI = window.SdlcBaseUI = { ...(window.PdlcBaseUI || window.SdlcBaseUI), requestConfirmation };
})();
