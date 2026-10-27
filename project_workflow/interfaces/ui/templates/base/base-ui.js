(() => {
  // Native pages use one replaceable message per host. React keeps Sonner's
  // event store; this adapter needs neither React nor a second product timer.
  const notifications = new WeakMap();
  /** @param {string} message @param {import('../src/runtime-globals').ServerNotificationOptions} options */
  function notify(message, options = {}) {
    const host = document.getElementById(options.hostId || 'base-toaster');
    const template = /** @type {HTMLTemplateElement} */ (host?.querySelector('[data-base-toast-template]'));
    if (!host?.hasAttribute('data-base-toaster') || !template) throw new Error('Base notification host is missing');
    const type = options.type ?? 'normal';
    if (!['normal', 'success', 'error', 'warning'].includes(type)) throw new TypeError('Unknown Base notification type');
    const duration = options.duration ?? (type === 'error' || type === 'warning' ? Infinity : 4000);
    if (!(duration === Infinity || Number.isFinite(duration) && duration >= 0 && duration <= 2147483647)) throw new TypeError('Invalid Base notification duration');
    const wasFocused = host.contains(document.activeElement);
    const previous = notifications.get(host);
    const trigger = wasFocused ? previous?.trigger : document.activeElement;
    previous?.dismiss(false);
    const panel = /** @type {HTMLElement} */ (template.content.firstElementChild.cloneNode(true));
    const close = /** @type {HTMLButtonElement} */ (panel.querySelector('[data-base-toast-close]'));
    panel.dataset.type = type;
    panel.querySelector('[data-base-toast-message]').textContent = String(message);
    host.querySelector(type === 'error' || type === 'warning' ? '[data-base-toast-alert]' : '[data-base-toast-status]').append(panel);
    let timer;
    let started = 0;
    let remaining = duration;
    let hovered = false;
    let active = true;
    function pause() {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
        remaining = Math.max(0, remaining - (Date.now() - started));
      }
    }
    function resume() {
      if (!active || hovered || document.hidden || panel.contains(document.activeElement) || remaining === Infinity || timer !== undefined) return;
      started = Date.now();
      timer = setTimeout(() => dismiss(), remaining);
    }
    function onEnter() { hovered = true; pause(); }
    function onLeave() { hovered = false; resume(); }
    function onFocusOut(event) { if (!panel.contains(event.relatedTarget)) queueMicrotask(resume); }
    function onVisibility() { if (document.hidden) pause(); else resume(); }
    function onClose() { dismiss(); }
    function onPageHide() { dismiss(false); }
    function dismiss(restoreFocus = true) {
      if (!active) return;
      active = false;
      pause();
      const focused = panel.contains(document.activeElement);
      panel.remove();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      // An obsolete dismiss handle must never remove a newer notification.
      if (notifications.get(host)?.dismiss === dismiss) notifications.delete(host);
      if (focused && restoreFocus) {
        if (trigger?.isConnected && typeof trigger.focus === 'function') trigger.focus();
        if (document.activeElement === document.body) /** @type {HTMLElement} */ (document.querySelector('main[tabindex="-1"]'))?.focus();
      }
    }
    panel.addEventListener('pointerenter', onEnter);
    panel.addEventListener('pointerleave', onLeave);
    panel.addEventListener('focusin', pause);
    panel.addEventListener('focusout', onFocusOut);
    close.addEventListener('click', onClose);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    notifications.set(host, { dismiss, trigger });
    if (wasFocused) close.focus();
    resume();
    return () => dismiss();
  }
  window.PdlcBaseUI = window.SdlcBaseUI = { ...(window.PdlcBaseUI || window.SdlcBaseUI), notify };
})();

// Dynamic SSR work areas reuse menu behavior without retaining removed DOM.
const menuControllers = new Map();
function destroyMenus(root) {
  for (const [menu, dispose] of menuControllers) {
    if (!menu.isConnected || root && (menu === root || root.contains(menu))) {
      dispose(); menuControllers.delete(menu);
    }
  }
}
function initMenus(root = document) {
  destroyMenus();
  const menus = /** @type {NodeListOf<HTMLDetailsElement>} */ (root.querySelectorAll('.base-ssr-account,[data-base-menu]'));
  for (const account of menus) {
    if (menuControllers.has(account)) continue;
    const abort = new AbortController();
    const listen = (target, type, callback, options = {}) => target.addEventListener(type, callback, { ...(typeof options === 'boolean' ? {capture:options} : options), signal:abort.signal });
    let resizeObserver;
    const toggle = account.querySelector('summary');
    const panel = /** @type {HTMLElement} */ (account.querySelector(':scope > [data-base-menu-content]'));
    let pointerInAccount = false;
    function closeAccount(restoreFocus) { account.open = false; if (restoreFocus) toggle?.focus(); }
    function positionPanel() {
      if (!account.open || !panel || !toggle) return;
      // Native disclosure positioning shares viewport bounds with the React
      // popup, without importing React/Popper into server-rendered pages.
      const padding = 8;
      const anchor = toggle.getBoundingClientRect();
      const below = Math.max(0, window.innerHeight - anchor.bottom - padding - 4);
      const above = Math.max(0, anchor.top - padding - 4);
      const flip = below < panel.scrollHeight && above > below;
      panel.style.top = flip ? 'auto' : 'calc(100% + 4px)';
      panel.style.bottom = flip ? 'calc(100% + 4px)' : 'auto';
      panel.style.maxHeight = Math.min(flip ? above : below, window.innerHeight * .8) + 'px';
      panel.style.translate = '0px';
      const bounds = panel.getBoundingClientRect();
      const width = document.documentElement.clientWidth;
      const shift = bounds.left < padding ? padding - bounds.left : Math.min(0, width - padding - bounds.right);
      panel.style.translate = shift + 'px';
    }
    listen(account, 'toggle', () => {
      const group = account.dataset.baseMenuGroup;
      if (account.open && group) for (const other of /** @type {NodeListOf<HTMLDetailsElement>} */ (document.querySelectorAll('.base-ssr-account,[data-base-menu]'))) {
        if (other !== account && other.dataset.baseMenuGroup === group) other.open = false;
      }
      positionPanel();
    });
    if (panel) {
      listen(window, 'resize', positionPanel);
      listen(document, 'scroll', positionPanel, true);
      // Published font/density changes can resize an already-open popup.
      if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(positionPanel); resizeObserver.observe(panel); }
    }
    // WebKit focuses an ancestor main before clicking a non-focusable link.
    // Keep the pressed menu item mounted until its click can be delivered.
    listen(document, 'pointerdown', (event) => { pointerInAccount = event.target instanceof Node && account.contains(event.target); });
    listen(document, 'pointerup', () => { pointerInAccount = false; });
    listen(document, 'pointercancel', () => { pointerInAccount = false; });
    listen(account, 'keydown', (event) => { if (event.key === 'Escape' && account.open) { event.preventDefault(); event.stopPropagation(); closeAccount(true); } });
    listen(document, 'click', (event) => { if (event.target instanceof Node && !account.contains(event.target)) closeAccount(false); });
    listen(account, 'focusout', (event) => { if (!pointerInAccount && event.relatedTarget instanceof Node && !account.contains(event.relatedTarget)) closeAccount(false); });
    menuControllers.set(account, () => { abort.abort(); resizeObserver?.disconnect(); });
  }
}
window.PdlcBaseUI = window.SdlcBaseUI = { ...(window.PdlcBaseUI || window.SdlcBaseUI), initMenus, destroyMenus };

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
  initMenus();
  const trigger = /** @type {HTMLElement} */ (document.querySelector('[data-base-drawer-trigger]'));
  const drawer = /** @type {HTMLDialogElement} */ (document.querySelector('[data-base-drawer]'));
  if (!trigger || !drawer) return;
  const focusable = () => /** @type {HTMLElement[]} */ ([...drawer.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')]).filter((item) => item.tabIndex >= 0 && !/** @type {HTMLButtonElement} */ (item).disabled && !item.closest('[inert]') && item.getClientRects().length);
  let previousOverflow = '';
  function finishClose() {
    if (trigger.getAttribute('aria-expanded') !== 'true') return;
    trigger.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = previousOverflow;
    for (const disclosure of drawer.querySelectorAll('details[open]')) disclosure.removeAttribute('open');
    const target = trigger.getClientRects().length ? trigger : /** @type {HTMLElement} */ (document.querySelector('main[tabindex="-1"]'));
    target?.focus();
  }
  function close() { if (drawer.open) drawer.close(); finishClose(); }
  window.PdlcBaseUI.closeNavigation = close;
  trigger.addEventListener('click', () => {
    if (drawer.open) return;
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    trigger.setAttribute('aria-expanded', 'true');
    drawer.showModal();
    focusable()[0]?.focus();
  });
  drawer.addEventListener('close', finishClose);
  drawer.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
  drawer.addEventListener('click', (event) => { if (event.target instanceof Element && event.target.closest('[data-base-drawer-close],a[href]')) close(); });
  drawer.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (!items.length) { event.preventDefault(); return; }
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
  });
  const desktop = window.matchMedia('(min-width: 768px)');
  const navigation = document.querySelector('[data-base-navigation-content]');
  const navigationHome = document.querySelector('[data-base-desktop-navigation]');
  const navigationSlot = drawer.querySelector('[data-base-navigation-slot]');
  const context = document.querySelector('[data-base-responsive-context]');
  const contextHome = document.querySelector('[data-base-context-home]');
  const contextSlot = drawer.querySelector('[data-base-navigation-context-slot]');
  function syncNavigation() {
    const hadFocus = navigation?.contains(document.activeElement) || context?.contains(document.activeElement);
    if (desktop.matches && drawer.open) close();
    for (const [content, home, mobileSlot] of [[navigation, navigationHome, navigationSlot], [context, contextHome, contextSlot]]) {
      const target = desktop.matches ? home : mobileSlot;
      if (content && target && content.parentElement !== target) {
        for (const disclosure of content.querySelectorAll('details[open]')) disclosure.removeAttribute('open');
        target.appendChild(content);
      }
    }
    if (!desktop.matches && hadFocus && !drawer.open) trigger.focus();
  }
  syncNavigation();
  desktop.addEventListener('change', syncNavigation);
  window.PdlcBaseUI = window.SdlcBaseUI = { ...(window.PdlcBaseUI || window.SdlcBaseUI), closeNavigation: close };
})();

(() => {
function requestConfirmation(options){
  if(document.querySelector('[data-base-drawer][open]')) window.PdlcBaseUI?.closeNavigation?.();
  var dialog = document.getElementById('confirmDialog');
  var cancel = document.getElementById('confirmDialogCancel');
  var accept = document.getElementById('confirmDialogAccept');
  var trigger = /** @type {HTMLElement} */ (document.activeElement);
  // A modal dismisses its source disclosure; restore to the visible summary,
  // not an action that is hidden inside the now-closed menu.
  var sourceMenu = trigger?.closest('details[data-base-menu][open]');
  if(sourceMenu){ trigger = sourceMenu.querySelector('summary'); sourceMenu.removeAttribute('open'); }
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
      if(document.activeElement !== trigger) /** @type {HTMLElement} */ (document.querySelector('main[tabindex="-1"]'))?.focus();
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
