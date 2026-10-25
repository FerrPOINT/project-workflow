import { isHex as hex, contrast, foreground } from "./branding-colors.js";
import { brandingFavicon, paintBrandingMark } from "./branding-marks.js";
import { DEFAULT_PLATFORM_NAME } from "./platform-title.js";

/** @typedef { {version: 1, font_preset: 'system'|'inter'|'noto-sans', type_scale: 'standard'|'large', density: 'compact'|'standard'|'comfortable', radius: 'square'|'standard'|'rounded', colors?: Record<string,{primary:string,accent:string}>, radii?: Record<'control'|'menu'|'dialog'|'card'|'mark',number>, marks?: Record<string,any>, favicon?: any, documentation_url?: string, initial_theme?: 'dark'|'gray'|'light'} } BrandingDesign */
/** @typedef { {product_name: string, product_short_name: string, logo_url: string|null, favicon_url: string|null, support_url: string|null, primary_color: string, accent_color: string, surface_color: string|null, design?: BrandingDesign|null} } Branding */
/** @typedef { {revision: number, updated_at: string, branding: Branding} } BrandingDocument */

/** Versioned presentation choices. No executable CSS or arbitrary font URLs enter the document. */
export const brandingPresets = {
  version: [1],
  font_preset: ["system", "inter", "noto-sans"],
  type_scale: ["standard", "large"],
  density: ["compact", "standard", "comfortable"],
  radius: ["square", "standard", "rounded"],
};
/** @type {Branding} */
export const defaultBranding = {
  product_name: DEFAULT_PLATFORM_NAME,
  product_short_name: DEFAULT_PLATFORM_NAME,
  logo_url: null,
  favicon_url: null,
  support_url: null,
  primary_color: "#2563eb",
  accent_color: "#14b8a6",
  surface_color: null,
};
/** @type {BrandingDesign} */
export const defaultDesign = {
  version: 1,
  font_preset: "system",
  type_scale: "standard",
  density: "standard",
  radius: "standard",
};

// Canonical color declarations; generate-design-tokens.mjs exports these to CSS.
const themes = {
  dark: {
    background: "#09090b",
    surface: "#18181b",
    "surface-raised": "#27272a",
    border: "#27272a",
    "border-strong": "#3f3f46",
    "text-primary": "#fafafa",
    "text-secondary": "#d4d4d8",
    "text-muted": "#a1a1aa",
    danger: "#f87171",
    success: "#4ade80",
    warning: "#fbbf24",
    "destructive-foreground": "#18181b",
  },
  gray: {
    background: "#1f1f23",
    surface: "#2a2a2f",
    "surface-raised": "#3f3f46",
    border: "#3f3f46",
    "border-strong": "#52525b",
    "text-primary": "#f4f4f5",
    "text-secondary": "#e4e4e7",
    "text-muted": "#b4b4bd",
    danger: "#fca5a5",
    success: "#86efac",
    warning: "#fde047",
    "destructive-foreground": "#18181b",
  },
  light: {
    background: "#f4f4f5",
    surface: "#ffffff",
    "surface-raised": "#f4f4f5",
    border: "#e4e4e7",
    "border-strong": "#d4d4d8",
    "text-primary": "#18181b",
    "text-secondary": "#3f3f46",
    "text-muted": "#52525b",
    danger: "#b91c1c",
    success: "#166534",
    warning: "#92400e",
    "destructive-foreground": "#ffffff",
  },
};
const channels = (color) =>
  [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
const mix = (a, b, amount) =>
  "#" +
  channels(a)
    .map((v, i) =>
      Math.round(v * (1 - amount) + channels(b)[i] * amount)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("");
/** The smallest deterministic sRGB adjustment meeting the role's contrast floor. */
function readable(seed, backgrounds, ratio) {
  if (backgrounds.every((bg) => contrast(seed, bg) >= ratio)) return seed;
  const target = foreground(backgrounds[0]);
  for (let step = 1; step <= 100; step++) {
    const value = mix(seed, target, step / 100);
    if (backgrounds.every((bg) => contrast(value, bg) >= ratio)) return value;
  }
  return target;
}

/** The same URL boundary is used by wire readers and the interactive editor. */
export function validBrandUrl(value) {
  if (!value) return true;
  if (
    typeof value !== "string" ||
    value.length > 2048 ||
    value.includes("\\") ||
    /\p{Cc}/u.test(value)
  )
    return false;
  try {
    const url = new URL(value);
    return (
      !url.username &&
      !url.password &&
      (url.protocol === "https:" ||
        (url.protocol === "http:" &&
          (["localhost", "[::1]"].includes(url.hostname) ||
            /^127(?:\.\d{1,3}){3}$/.test(url.hostname))))
    );
  } catch {
    return false;
  }
}
const record = (value) =>
  !!value && typeof value === "object" && !Array.isArray(value);
const iconIds = [
  "layers",
  "box",
  "compass",
  "globe",
  "hexagon",
  "network",
  "rocket",
  "shield",
  "terminal",
  "workflow",
  "cpu",
  "activity",
  "leaf",
  "sparkles",
  "circle-dot",
  "flask",
];
function validAsset(value, branding) {
  return (
    value === null ||
    (record(value) &&
      typeof value.id === "string" &&
      (/^[a-f0-9]{64}$/.test(value.id) ||
        (value.id === "legacy-logo" && value.url === branding.logo_url) ||
        (value.id === "legacy-favicon" &&
          value.url === branding.favicon_url)) &&
      typeof value.url === "string" &&
      !!value.url &&
      validBrandUrl(value.url) &&
      typeof value.name === "string" &&
      value.name.length <= 255)
  );
}
function validMark(mark, branding) {
  if (
    !record(mark) ||
    !["letters", "icon", "image"].includes(mark.kind) ||
    ![1, 2, 4].includes(mark.count) ||
    typeof mark.letters !== "string" ||
    mark.letters.length > 128 ||
    !iconIds.includes(mark.icon) ||
    !hex(mark.foreground) ||
    !hex(mark.background) ||
    !["square", "rounded", "circle"].includes(mark.shape) ||
    !["contain", "cover"].includes(mark.fit) ||
    !validAsset(mark.image, branding)
  )
    return false;
  if (mark.kind === "image") return !!mark.image;
  if (contrast(mark.foreground, mark.background) < 4.5) return false;
  if (mark.kind !== "letters") return true;
  const letters = Array.from(
    new Intl.Segmenter("ru", { granularity: "grapheme" }).segment(mark.letters),
    (part) => part.segment,
  );
  return (
    letters.length === mark.count &&
    letters.every(
      (letter) =>
        !/[\s\p{Cc}]/u.test(letter) && !/^[\p{M}\p{C}]+$/u.test(letter),
    )
  );
}
function validExpandedDesign(design, branding) {
  if (
    !record(design.marks) ||
    !validMark(design.marks.common, branding) ||
    ![design.marks.light, design.marks.dark].every(
      (mark) => mark === null || validMark(mark, branding),
    ) ||
    !record(design.favicon) ||
    !["auto", "logo", "image"].includes(design.favicon.mode) ||
    !validAsset(design.favicon.image, branding) ||
    (design.favicon.mode === "image" && !design.favicon.image) ||
    !record(design.colors) ||
    !record(design.radii) ||
    !["dark", "gray", "light"].includes(design.initial_theme) ||
    typeof design.documentation_url !== "string" ||
    !validBrandUrl(design.documentation_url)
  )
    return false;
  for (const mode of ["dark", "gray", "light"]) {
    const colors = design.colors[mode];
    if (!record(colors) || !hex(colors.primary) || !hex(colors.accent))
      return false;
    if (
      [themes[mode].background, themes[mode].surface].some(
        (background) =>
          contrast(colors.primary, background) < 3 ||
          contrast(colors.accent, background) < 4.5,
      )
    )
      return false;
  }
  for (const [key, max] of Object.entries({
    control: 12,
    menu: 16,
    dialog: 24,
    card: 24,
    mark: 16,
  }))
    if (
      !Number.isInteger(design.radii[key]) ||
      design.radii[key] < 0 ||
      design.radii[key] > max
    )
      return false;
  return true;
}

/** Reject unsupported design versions instead of silently dropping their settings. */
export function normalizeBranding(payload) {
  if (!payload || typeof payload !== "object") return null;
  const value = /** @type {Record<string, any>} */ (payload);
  if (
    typeof value.product_name !== "string" ||
    !value.product_name.trim() ||
    typeof value.product_short_name !== "string" ||
    !value.product_short_name.trim() ||
    !hex(value.primary_color) ||
    !hex(value.accent_color)
  )
    return null;
  if (value.surface_color != null && !hex(value.surface_color)) return null;
  if (
    new TextEncoder().encode(value.product_name).length > 80 ||
    new TextEncoder().encode(value.product_short_name).length > 24
  )
    return null;
  for (const key of ["logo_url", "favicon_url", "support_url"])
    if (
      value[key] != null &&
      (typeof value[key] !== "string" || !validBrandUrl(value[key]))
    )
      return null;
  if (value.design != null) {
    if (typeof value.design !== "object") return null;
    const expanded = Object.hasOwn(value.design, "marks");
    for (const [key, allowed] of Object.entries(brandingPresets)) {
      const choice =
        key !== "version" && value.design[key] === undefined
          ? defaultDesign[key]
          : value.design[key];
      if (!allowed.some((item) => item === choice)) return null;
    }
    if (expanded && !validExpandedDesign(value.design, value)) return null;
  }
  return /** @type {Branding} */ ({
    product_name: value.product_name,
    product_short_name: value.product_short_name,
    logo_url: typeof value.logo_url === "string" ? value.logo_url : null,
    favicon_url:
      typeof value.favicon_url === "string" ? value.favicon_url : null,
    support_url:
      typeof value.support_url === "string" ? value.support_url : null,
    primary_color: value.primary_color,
    accent_color: value.accent_color,
    surface_color: value.surface_color ?? null,
    design: { ...defaultDesign, ...(value.design ?? {}) },
  });
}

/** Pure presentation compiler shared by React, SSR, static pages and previews. */
export function resolveBrandingTokens(branding, theme = "dark") {
  const value = normalizeBranding(branding);
  if (!value) throw new Error("Unsupported or invalid branding document");
  const mode = Object.hasOwn(themes, theme) ? theme : "dark";
  const colors = { ...themes[mode] };
  const selected = value.design?.colors?.[mode];
  const primary = selected?.primary ?? value.primary_color;
  const accent = selected?.accent ?? value.accent_color;
  if (value.surface_color)
    for (const key of ["background", "surface", "surface-raised"])
      colors[key] = mix(colors[key], value.surface_color, 0.08);
  const selectionSurface = mix(colors.surface, accent, 0.14);
  // Semantic descendants also render on selected rows and resource choices.
  const backgrounds = [
    colors.background,
    colors.surface,
    colors["surface-raised"],
    selectionSurface,
  ];
  for (const key of [
    "text-primary",
    "text-secondary",
    "text-muted",
    "danger",
    "success",
    "warning",
  ])
    colors[key] = readable(colors[key], backgrounds, 4.5);
  colors["border-strong"] = readable(colors["border-strong"], backgrounds, 3);
  const action = readable(primary, backgrounds, 4.5);
  const highlight = readable(accent, backgrounds, 4.5);
  const design = value.design ?? defaultDesign;
  const large = design.type_scale === "large";
  const radius =
    design.radii?.control ??
    { square: 0, standard: 6, rounded: 12 }[design.radius];
  const density = design.density;
  const tokens = Object.fromEntries(
    Object.entries(colors).map(([key, color]) => ["--color-" + key, color]),
  );
  Object.assign(tokens, {
    "--platform-primary": primary,
    "--platform-primary-foreground": foreground(primary),
    "--platform-accent": accent,
    "--platform-surface": value.surface_color ?? colors.surface,
    "--color-accent": action,
    "--color-accent-foreground": foreground(action),
    "--color-accent-hover": mix(
      action,
      mode === "light" ? "#000000" : "#ffffff",
      0.12,
    ),
    "--color-accent-hover-foreground": foreground(
      mix(action, mode === "light" ? "#000000" : "#ffffff", 0.12),
    ),
    "--color-highlight": highlight,
    "--color-selection": selectionSurface,
    "--color-selection-foreground": readable(
      colors["text-primary"],
      [selectionSurface],
      4.5,
    ),
    "--color-focus": readable(action, backgrounds, 3),
    "--color-primary": action,
    "--color-primary-foreground": foreground(action),
    "--color-secondary": colors["surface-raised"],
    "--color-secondary-foreground": colors["text-primary"],
    "--color-muted": colors["surface-raised"],
    "--color-muted-foreground": colors["text-muted"],
    "--color-destructive": colors.danger,
    "--color-popover": colors.surface,
    "--color-popover-foreground": colors["text-primary"],
    "--base-font-sans": {
      system:
        'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      inter: '"PDLC Inter", system-ui, sans-serif',
      "noto-sans": '"PDLC Noto Sans", system-ui, sans-serif',
    }[design.font_preset],
    "--base-font-body": large ? "16px" : "14px",
    "--base-font-label": large ? "14px" : "12px",
    "--base-font-page-title": large ? "28px" : "24px",
    "--base-line-body": large ? "24px" : "20px",
    "--base-radius": radius + "px",
    "--radius-sm": Math.max(0, radius - 2) + "px",
    "--radius-md": radius + "px",
    "--radius-lg": (radius ? radius + 2 : 0) + "px",
    "--radius-xl": (radius ? radius + 4 : 0) + "px",
    "--base-control-padding-inline": {
      compact: "12px",
      standard: "16px",
      comfortable: "20px",
    }[density],
    "--base-control-padding-block": {
      compact: "4px",
      standard: "8px",
      comfortable: "12px",
    }[density],
    "--base-row-height": {
      compact: "40px",
      standard: "48px",
      comfortable: "56px",
    }[density],
    "--base-panel-padding": {
      compact: "12px",
      standard: "20px",
      comfortable: "24px",
    }[density],
    "--shell-control-min": density === "comfortable" || large ? "44px" : "40px",
    "--shell-control-mobile-min": "44px",
  });
  Object.assign(tokens, {
    "--base-radius-card":
      (design.radii?.card ?? (radius ? radius + 2 : 0)) + "px",
    "--base-radius-dialog":
      (design.radii?.dialog ?? (radius ? radius + 2 : 0)) + "px",
    "--base-radius-menu": (design.radii?.menu ?? radius) + "px",
    ...Object.fromEntries(
      Object.entries(design.radii ?? {}).map(([key, value]) => [
        "--brand-radius-" + key,
        value + "px",
      ]),
    ),
  });
  return tokens;
}

/**
 * One document-scoped reader. Caches are tied to the explicit URL and origin;
 * disposal invalidates old responses and restores only properties this reader owned.
 * @param { {root: HTMLElement, configUrl: string|null, defaults?: Branding, fetcher?: typeof fetch, storage?: Storage|null, onChange?: (state: {branding: Branding, revision: number|null, source: 'runtime'|'cache'|'defaults'})=>void, intervalMs?: number, getAccessToken?: ()=>string|null|undefined} } options
 */
export function createBrandingRuntime(options) {
  const {
    root,
    defaults = defaultBranding,
    onChange = () => {},
    intervalMs = 60000,
  } = options;
  const win = root.ownerDocument.defaultView;
  const configUrl = options.configUrl
    ? new URL(options.configUrl, root.ownerDocument.baseURI).href
    : null;
  const key = configUrl
    ? "pdlc.branding.v1:" + win.location.origin + ":" + configUrl
    : null;
  let storage = options.storage;
  if (storage === undefined)
    try {
      storage = win.localStorage;
    } catch {
      storage = null;
    }
  let active = true,
    sequence = 0,
    etag = null,
    revision = null,
    branding = normalizeBranding(defaults),
    source = /** @type {'runtime'|'cache'|'defaults'} */ ("defaults");
  if (!branding) throw new Error("Invalid default branding");
  /** @type {Map<string, {value:string, priority:string}>} */ const previous =
    new Map();
  const controller = new AbortController();
  function documentValue(input) {
    if (
      !input ||
      typeof input !== "object" ||
      !Number.isInteger(input.revision) ||
      input.revision < 0
    )
      return null;
    const normalized = normalizeBranding(input.branding);
    return normalized ? { ...input, branding: normalized } : null;
  }
  if (key && storage)
    try {
      const cached = JSON.parse(storage.getItem(key) || "null");
      const doc = documentValue(cached?.document);
      if (doc && typeof cached.etag === "string") {
        branding = doc.branding;
        revision = doc.revision;
        etag = cached.etag;
        source = "cache";
      }
    } catch {
      /* Invalid/unavailable local caches cannot prevent opening a product. */
    }
  function paint() {
    if (!active) return;
    const tokens = resolveBrandingTokens(branding, root.dataset.theme);
    for (const [name, value] of Object.entries(tokens)) {
      if (!previous.has(name))
        previous.set(name, {
          value: root.style.getPropertyValue(name),
          priority: root.style.getPropertyPriority(name),
        });
      root.style.setProperty(name, value);
    }
  }
  let generatedIcon = null;
  const originalIcons =
    root === root.ownerDocument.documentElement
      ? new Map(
          [
            ...root.ownerDocument.querySelectorAll(
              'link[rel="icon"],link[rel="shortcut icon"]',
            ),
          ].map((link) => [link, link.getAttribute("href") ?? ""]),
        )
      : new Map();
  const safeImage = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) &&
        !url.username &&
        !url.password
        ? url.href
        : null;
    } catch {
      return null;
    }
  };
  const originalMarks = new Map();
  let identitySequence = 0;
  function identity() {
    if (!active) return;
    for (const title of root.querySelectorAll("[data-base-brand-title]"))
      title.textContent =
        (title.getAttribute("data-base-brand-title") || "PDLC") +
        " — " +
        branding.product_short_name;
    for (const element of root.querySelectorAll("[data-base-brand-name]"))
      element.textContent = branding.product_name;
    for (const element of root.querySelectorAll("[data-base-brand-initials]"))
      element.textContent = branding.product_short_name
        .slice(0, 2)
        .toUpperCase();
    for (const mark of root.querySelectorAll("[data-base-platform-mark]")) {
      if (branding.design?.marks) {
        if (!originalMarks.has(mark))
          originalMarks.set(mark, {
            nodes: Array.from(mark.childNodes),
            style: mark.getAttribute("style"),
            role: mark.getAttribute("role"),
            label: mark.getAttribute("aria-label"),
          });
        paintBrandingMark(mark, branding, root.dataset.theme);
        continue;
      }
      if (originalMarks.has(mark)) {
        const original = originalMarks.get(mark);
        mark.replaceChildren(...original.nodes);
        for (const [name, value] of [
          ["style", original.style],
          ["role", original.role],
          ["aria-label", original.label],
        ])
          if (value === null) mark.removeAttribute(name);
          else mark.setAttribute(name, value);
        originalMarks.delete(mark);
      }
      const image = mark.querySelector("img");
      const initials = mark.querySelector("[data-base-brand-initials]");
      const url = safeImage(branding.logo_url);
      if (image) {
        image.hidden = !url;
        if (url) image.setAttribute("src", url);
        else image.removeAttribute("src");
      }
      if (initials instanceof win.HTMLElement) initials.hidden = !!url;
    }
    const identityRequest = ++identitySequence;
    if (branding.design?.marks && root === root.ownerDocument.documentElement) {
      if (!originalIcons.size) {
        generatedIcon = root.ownerDocument.createElement("link");
        generatedIcon.rel = "icon";
        root.ownerDocument.head.appendChild(generatedIcon);
        originalIcons.set(generatedIcon, "");
      }
      void brandingFavicon(branding, root.dataset.theme)
        .then((url) => {
          if (active && identityRequest === identitySequence && url)
            for (const [link] of originalIcons) link.setAttribute("href", url);
        })
        .catch(() => {
          /* Retain the confirmed icon when canvas is unavailable. */
        });
    } else
      for (const [link, original] of originalIcons)
        link.setAttribute("href", safeImage(branding.favicon_url) ?? original);
  }
  root.ownerDocument.addEventListener("DOMContentLoaded", identity);
  function publish() {
    paint();
    identity();
    onChange({ branding, revision, source });
  }
  publish();
  const observer = new win.MutationObserver(() => {
    paint();
    identity();
  });
  observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  async function refresh() {
    if (!active || !configUrl) return;
    const request = ++sequence;
    const fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
    /** @type {Record<string,string>} */ const headers = etag
      ? { "If-None-Match": etag }
      : {};
    const token = options.getAccessToken?.();
    if (token) headers.Authorization = "Bearer " + token;
    try {
      const response = await fetcher(options.configUrl, {
        headers,
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      if (!active || request !== sequence) return;
      if (response.status === 304) return; // An ETag exists only alongside this reader's validated document.
      if (!response.ok) return;
      const doc = documentValue(await response.json());
      if (!active || request !== sequence || !doc) return;
      branding = doc.branding;
      revision = doc.revision;
      etag = response.headers.get("etag");
      source = "runtime";
      if (key && storage)
        try {
          storage.setItem(
            key,
            JSON.stringify({ etag: etag ?? "", document: doc }),
          );
        } catch {
          /* Presentation still applies if quota or storage policy prevents caching. */
        }
      publish();
    } catch {
      /* Keep the last confirmed presentation; never turn a read failure into a reset. */
    }
  }
  const visible = () => {
    if (root.ownerDocument.visibilityState === "visible") void refresh();
  };
  const timer = configUrl ? win.setInterval(visible, intervalMs) : null;
  root.ownerDocument.addEventListener("visibilitychange", visible);
  win.addEventListener("focus", visible);
  void refresh();
  return {
    refresh,
    applyPublished(payload, validator) {
      if (!active || !configUrl) return false;
      const doc = documentValue(payload);
      if (!doc || (revision !== null && doc.revision < revision)) return false;
      sequence++;
      branding = doc.branding;
      revision = doc.revision;
      etag = validator ?? null;
      source = "runtime";
      if (key && storage)
        try {
          storage.setItem(
            key,
            JSON.stringify({ etag: etag ?? "", document: doc }),
          );
        } catch {
          /* Storage is optional. */
        }
      publish();
      return true;
    },
    dispose() {
      active = false;
      sequence++;
      controller.abort();
      observer.disconnect();
      for (const [mark, original] of originalMarks) {
        mark.replaceChildren(...original.nodes);
        for (const [name, value] of [
          ["style", original.style],
          ["role", original.role],
          ["aria-label", original.label],
        ])
          if (value === null) mark.removeAttribute(name);
          else mark.setAttribute(name, value);
      }
      root.ownerDocument.removeEventListener("DOMContentLoaded", identity);
      for (const [link, original] of originalIcons)
        link.setAttribute("href", original);
      generatedIcon?.remove();
      if (timer !== null) win.clearInterval(timer);
      root.ownerDocument.removeEventListener("visibilitychange", visible);
      win.removeEventListener("focus", visible);
      for (const [name, old] of previous) {
        if (old.value) root.style.setProperty(name, old.value, old.priority);
        else root.style.removeProperty(name);
      }
    },
  };
}
