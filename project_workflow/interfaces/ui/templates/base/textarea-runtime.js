/** @typedef { {refresh:()=>void, destroy:()=>void}} TextareaAutosizeController */
/** @type {WeakMap<HTMLTextAreaElement, TextareaAutosizeController>} */
const controls = new WeakMap();

/**
 * Shared, opt-in measurement for React and native pages. It never changes the
 * value, selection, focus or form events. Refresh after an imperative value or
 * parent change; destroy before removing a native control.
 * @param {HTMLTextAreaElement} field
 * @returns {TextareaAutosizeController | undefined}
 */
export function initTextareaAutosize(field) {
  const previous = controls.get(field);
  if (previous) {
    previous.refresh();
    return previous;
  }
  const doc = field.ownerDocument;
  const win = doc.defaultView;
  if (!win) return;
  const originalHeight = field.style.getPropertyValue("height");
  const priority = field.style.getPropertyPriority("height");
  let active = true;
  let signature = "";
  let ownedHeight = "";
  let ownedStyle = field.getAttribute("style");
  /** @type {number | undefined} */
  let frame;
  /** @type {Element[]} */
  let parents = [];
  const fontProperties = [
    "box-sizing",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "line-height",
    "letter-spacing",
    "word-spacing",
    "white-space",
    "word-break",
    "overflow-wrap",
    "text-indent",
    "padding-top",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "border-top-width",
    "border-bottom-width",
    "min-height",
    "max-height",
  ];

  function measure() {
    if (!active || !field.isConnected || !field.getClientRects().length) return;
    const style = win.getComputedStyle(field);
    const next = JSON.stringify([
      field.value,
      field.placeholder,
      field.rows,
      field.wrap,
      field.clientWidth,
      ...fontProperties.map((name) => style.getPropertyValue(name)),
    ]);
    if (next === signature) return;
    signature = next;
    const pixels = (name) => parseFloat(style.getPropertyValue(name)) || 0;
    const adjustment =
      style.boxSizing === "border-box"
        ? pixels("border-top-width") + pixels("border-bottom-width")
        : -pixels("padding-top") - pixels("padding-bottom");
    // Intrinsic rows and CSS min/max-height still constrain the browser's box.
    // Resetting first also permits shrinking after deletion or form reset.
    field.style.setProperty("height", "auto", priority);
    ownedHeight = `${Math.max(0, Math.ceil(field.scrollHeight + adjustment))}px`;
    field.style.setProperty("height", ownedHeight, priority);
    ownedStyle = field.getAttribute("style");
  }
  function schedule() {
    if (!active || frame !== undefined) return;
    frame = win.requestAnimationFrame(() => {
      frame = undefined;
      measure();
    });
  }
  const attributes = new win.MutationObserver((records) => {
    if (
      records.some(
        (record) =>
          record.target !== field ||
          record.attributeName !== "style" ||
          field.getAttribute("style") !== ownedStyle,
      )
    )
      schedule();
  });
  function observeParents() {
    if (form !== field.form) {
      form?.removeEventListener("reset", schedule);
      form = field.form;
      form?.addEventListener("reset", schedule);
    }
    /** @type {Element[]} */
    const next = [];
    for (
      let parent = field.parentElement;
      parent;
      parent = parent.parentElement
    )
      next.push(parent);
    if (
      parents.length === next.length &&
      parents.every((parent, index) => parent === next[index])
    )
      return;
    parents = next;
    attributes.disconnect();
    attributes.observe(field, {
      attributes: true,
      attributeFilter: [
        "style",
        "class",
        "rows",
        "wrap",
        "placeholder",
        "hidden",
      ],
    });
    for (const parent of parents)
      attributes.observe(parent, {
        attributes: true,
        attributeFilter: ["style", "class", "data-theme", "hidden", "open"],
      });
  }
  let width;
  const resize =
    typeof win.ResizeObserver === "undefined"
      ? null
      : new win.ResizeObserver((entries) => {
          const next = entries[0]?.contentRect.width;
          // Our own height writes must not create a resize/measurement loop.
          if (next !== width) {
            width = next;
            schedule();
          }
        });
  resize?.observe(field);
  let form = field.form;
  const fonts = doc.fonts;
  const pagehide = (event) => {
    if (!event.persisted) controller.destroy();
  };
  const controller = {
    refresh() {
      if (!active) return;
      observeParents();
      signature = "";
      measure();
    },
    destroy() {
      if (!active) return;
      active = false;
      if (frame !== undefined) win.cancelAnimationFrame(frame);
      attributes.disconnect();
      resize?.disconnect();
      field.removeEventListener("input", schedule);
      form?.removeEventListener("reset", schedule);
      fonts?.removeEventListener("loadingdone", fontChanged);
      win.removeEventListener("resize", schedule);
      win.removeEventListener("pagehide", pagehide);
      // Preserve a newer explicit height written by the owning application.
      if (
        field.style.getPropertyValue("height") === ownedHeight &&
        field.style.getPropertyPriority("height") === priority
      ) {
        if (originalHeight)
          field.style.setProperty("height", originalHeight, priority);
        else field.style.removeProperty("height");
      }
      controls.delete(field);
    },
  };
  function fontChanged() {
    signature = "";
    schedule();
  }
  controls.set(field, controller);
  field.addEventListener("input", schedule);
  form?.addEventListener("reset", schedule);
  fonts?.addEventListener("loadingdone", fontChanged);
  if (fonts) void fonts.ready.then(fontChanged);
  win.addEventListener("resize", schedule);
  win.addEventListener("pagehide", pagehide);
  controller.refresh();
  return controller;
}

/** @param {HTMLTextAreaElement} field */
export function refreshTextareaAutosize(field) {
  controls.get(field)?.refresh();
}
/** @param {HTMLTextAreaElement} field */
export function destroyTextareaAutosize(field) {
  controls.get(field)?.destroy();
}
