/** The only browser clipboard transport for React and SSR. No fallback, logging or retry. */
/** @param {string} value */
export async function writeClipboardText(value) {
  const clipboard = globalThis.navigator?.clipboard;
  if (typeof clipboard?.writeText !== "function")
    throw new Error("Clipboard API is unavailable");
  await clipboard.writeText(value);
}

/** @typedef { {copy:()=>Promise<boolean>,refresh:()=>void,destroy:()=>void} } CopyController */
/** @type {WeakMap<HTMLButtonElement, CopyController>} */
const controls = new WeakMap();

/**
 * Activate a macro-owned control. The source element and its exact text are read on activation.
 * Refresh after changing its resource; destroy before replacing a control that may still be pending.
 * @param {HTMLButtonElement} button
 * @param {Object} [options]
 * @param {(value:string)=>Promise<void>} [options.writeText] Synthetic test transport only.
 * @returns {CopyController | undefined}
 */
export function initCopyButton(button, options = {}) {
  const previous = controls.get(button);
  if (previous) return previous;
  const container = button.closest("[data-base-copy]");
  const status = container?.querySelector("[data-base-copy-status]");
  const error = container?.querySelector("[data-base-copy-error]");
  if (!status || !error) return;
  let active = true,
    busy = false,
    generation = 0;
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer;
  const label = () => button.dataset.baseCopyLabel || "Копировать";
  const clearFeedback = () => {
    clearTimeout(timer);
    status.textContent = "";
    error.textContent = "";
  };
  const idle = () => {
    button.removeAttribute("aria-busy");
    button.textContent = label();
  };
  const source = () =>
    button.ownerDocument.getElementById(button.dataset.baseCopyTarget || "");
  async function copy() {
    if (
      !active ||
      busy ||
      button.disabled ||
      button.getAttribute("aria-disabled") === "true"
    )
      return false;
    clearFeedback();
    const target = source();
    if (!target) {
      error.textContent = "Значение для копирования недоступно.";
      return false;
    }
    const value = target.textContent || "";
    const version = generation;
    busy = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Копирование…";
    let failed = false;
    try {
      await (options.writeText || writeClipboardText)(value);
    } catch {
      failed = true;
    }
    busy = false;
    if (!active) return false;
    idle();
    // Never acknowledge another resource or a removed/replaced source, even after a successful write.
    if (
      !button.isConnected ||
      !target.isConnected ||
      version !== generation ||
      source() !== target ||
      target.textContent !== value
    )
      return false;
    if (failed) {
      error.textContent =
        "Не удалось скопировать. Выделите значение и скопируйте вручную.";
      return false;
    }
    button.textContent = "Скопировано";
    status.textContent = "Скопировано";
    timer = setTimeout(() => {
      if (active) {
        idle();
        clearFeedback();
      }
    }, 1600);
    return true;
  }
  const click = () => {
    void copy();
  };
  const controller = {
    copy,
    refresh() {
      generation += 1;
      clearFeedback();
      if (!busy) idle();
    },
    destroy() {
      active = false;
      generation += 1;
      clearFeedback();
      idle();
      button.removeEventListener("click", click);
      controls.delete(button);
    },
  };
  controls.set(button, controller);
  button.addEventListener("click", click);
  return controller;
}

/** @param {HTMLButtonElement} button */
export function refreshCopyButton(button) {
  controls.get(button)?.refresh();
}
/** @param {HTMLButtonElement} button */
export function destroyCopyButton(button) {
  controls.get(button)?.destroy();
}
