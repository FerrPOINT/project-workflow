(function(){
const DEFAULT_PLATFORM_NAME = "PDLC";
/** @param {string} serviceLabel @param { {product_short_name?: string}} [branding] */
function platformTitle(serviceLabel, branding) {
  const name =
    (typeof branding?.product_short_name === "string" &&
      branding.product_short_name.trim()) ||
    DEFAULT_PLATFORM_NAME;
  return `${serviceLabel} — ${name}`;
}

function isHex(value) { return typeof value === "string" && /^#[a-f\d]{6}$/i.test(value); }
function luminance(color) {
 return [1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
}
function contrast(a,b) {
 if (!isHex(a) || !isHex(b)) return 0;
 const first=luminance(a),second=luminance(b);return (Math.max(first,second)+0.05)/(Math.min(first,second)+0.05);
}
function foreground(color) { return contrast(color,"#000000") >= contrast(color,"#ffffff") ? "#000000" : "#ffffff"; }

// Generated from pinned Lucide (ISC license) by generate-design-tokens.mjs.
const brandingIcons = {
  "layers": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-layers lucide-layers-3\" aria-hidden=\"true\"><path d=\"M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z\"></path><path d=\"M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12\"></path><path d=\"M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17\"></path></svg>",
  "box": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-box\" aria-hidden=\"true\"><path d=\"M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z\"></path><path d=\"m3.3 7 8.7 5 8.7-5\"></path><path d=\"M12 22V12\"></path></svg>",
  "compass": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-compass\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"10\"></circle><path d=\"m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z\"></path></svg>",
  "globe": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-globe\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"10\"></circle><path d=\"M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20\"></path><path d=\"M2 12h20\"></path></svg>",
  "hexagon": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-hexagon\" aria-hidden=\"true\"><path d=\"M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z\"></path></svg>",
  "network": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-network\" aria-hidden=\"true\"><rect x=\"16\" y=\"16\" width=\"6\" height=\"6\" rx=\"1\"></rect><rect x=\"2\" y=\"16\" width=\"6\" height=\"6\" rx=\"1\"></rect><rect x=\"9\" y=\"2\" width=\"6\" height=\"6\" rx=\"1\"></rect><path d=\"M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3\"></path><path d=\"M12 12V8\"></path></svg>",
  "rocket": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-rocket\" aria-hidden=\"true\"><path d=\"M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5\"></path><path d=\"M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09\"></path><path d=\"M9 12a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.4 22.4 0 0 1-4 2z\"></path><path d=\"M9 12H4s.55-3.03 2-4c1.62-1.08 5 .05 5 .05\"></path></svg>",
  "shield": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-shield\" aria-hidden=\"true\"><path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"></path></svg>",
  "terminal": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-terminal\" aria-hidden=\"true\"><path d=\"M12 19h8\"></path><path d=\"m4 17 6-6-6-6\"></path></svg>",
  "workflow": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-workflow\" aria-hidden=\"true\"><rect width=\"8\" height=\"8\" x=\"3\" y=\"3\" rx=\"2\"></rect><path d=\"M7 11v4a2 2 0 0 0 2 2h4\"></path><rect width=\"8\" height=\"8\" x=\"13\" y=\"13\" rx=\"2\"></rect></svg>",
  "cpu": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-cpu\" aria-hidden=\"true\"><path d=\"M12 20v2\"></path><path d=\"M12 2v2\"></path><path d=\"M17 20v2\"></path><path d=\"M17 2v2\"></path><path d=\"M2 12h2\"></path><path d=\"M2 17h2\"></path><path d=\"M2 7h2\"></path><path d=\"M20 12h2\"></path><path d=\"M20 17h2\"></path><path d=\"M20 7h2\"></path><path d=\"M7 20v2\"></path><path d=\"M7 2v2\"></path><rect x=\"4\" y=\"4\" width=\"16\" height=\"16\" rx=\"2\"></rect><rect x=\"8\" y=\"8\" width=\"8\" height=\"8\" rx=\"1\"></rect></svg>",
  "activity": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-activity\" aria-hidden=\"true\"><path d=\"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2\"></path></svg>",
  "leaf": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-leaf\" aria-hidden=\"true\"><path d=\"M11 20a10 10 0 0010-10 25.9 25.9 0 00-1.04-7.281 1 1 0 00-1.755-.325C15.833 5.5 13 5.5 9.8 6.1A7 7 0 0011 20\"></path><path d=\"M2 21a5 5 0 012.911-4.544C7.613 15.212 8.351 15.24 11 13\"></path></svg>",
  "sparkles": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-sparkles lucide-stars\" aria-hidden=\"true\"><path d=\"M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z\"></path><path d=\"M20 2v4\"></path><path d=\"M22 4h-4\"></path><circle cx=\"4\" cy=\"20\" r=\"2\"></circle></svg>",
  "circle-dot": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-circle-dot\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"1\"></circle><circle cx=\"12\" cy=\"12\" r=\"10\"></circle></svg>",
  "flask": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-flask-conical\" aria-hidden=\"true\"><path d=\"M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2\"></path><path d=\"M6.453 15h11.094\"></path><path d=\"M8.5 2h7\"></path></svg>"
};

function effectiveMark(document, theme) {
  return (
    document.design.marks[theme === "light" ? "light" : "dark"] ??
    document.design.marks.common
  );
}
function markLetters(document, mark) {
  return Array.from(
    new Intl.Segmenter("ru", { granularity: "grapheme" }).segment(
      mark.kind === "letters"
        ? mark.letters
        : (document.product_short_name || "PDLC").toUpperCase().padEnd(4, "P"),
    ),
    (part) => part.segment,
  );
}
function markCount(mark, compact, failed) {
  return failed || (compact && mark.count === 4) ? 1 : mark.count;
}
function markFontSize(count, size) {
  return size * (count === 4 ? 0.36 : count === 2 ? 0.38 : 0.56);
}
function fourLetterOffset(index, size) {
  return {
    x: size * 0.04 * (index % 2 === 0 ? 1 : -1),
    y: size * 0.04 * (index < 2 ? 1 : -1),
  };
}
async function brandingFavicon(brand, theme) {
  const mark = effectiveMark(brand, theme);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const safe = contrast(mark.foreground, mark.background) >= 4.5;
  const foreground = safe ? mark.foreground : "#ffffff";
  const radius =
    mark.shape === "circle"
      ? 32
      : mark.shape === "square"
        ? 0
        : brand.design.radii.mark;
  ctx.beginPath();
  ctx.roundRect(0, 0, 64, 64, radius);
  ctx.clip();
  ctx.fillStyle = safe ? mark.background : "#2563eb";
  ctx.fillRect(0, 0, 64, 64);
  const asset =
    brand.design.favicon.mode === "image"
      ? brand.design.favicon.image
      : mark.kind === "image"
        ? mark.image
        : null;
  const source =
    asset?.url ??
    (mark.kind === "icon" && brand.design.favicon.mode !== "image"
      ? "data:image/svg+xml," +
        encodeURIComponent(
          brandingIcons[mark.icon].replaceAll("currentColor", foreground),
        )
      : null);
  let failed = mark.kind === "image" && !source;
  if (source) {
    const image = new Image();
    image.crossOrigin = "anonymous";
    const loaded = await new Promise((resolve) => {
      const timeout = window.setTimeout(() => resolve(false), 2000);
      image.onload = () => {
        clearTimeout(timeout);
        resolve(true);
      };
      image.onerror = () => {
        clearTimeout(timeout);
        resolve(false);
      };
      image.src = source;
    });
    if (loaded) {
      const ratio =
        mark.kind === "icon" && !asset
          ? 0.6
          : mark.fit === "cover"
            ? Math.max(64 / image.width, 64 / image.height)
            : Math.min(64 / image.width, 64 / image.height);
      const width = mark.kind === "icon" && !asset ? 38.4 : image.width * ratio;
      const height =
        mark.kind === "icon" && !asset ? 38.4 : image.height * ratio;
      ctx.drawImage(image, (64 - width) / 2, (64 - height) / 2, width, height);
      try {
        return canvas.toDataURL("image/png");
      } catch {
        failed = true;
      }
    } else failed = true;
  }
  const count = markCount(mark, brand.design.favicon.mode !== "logo", failed);
  ctx.fillStyle = foreground;
  ctx.font = `700 ${brand.design.favicon.mode === "logo" ? markFontSize(count, 64) : count === 2 ? 24 : 36}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const letters = markLetters(brand, mark).slice(0, count);
  if (count === 4) {
    letters.forEach((letter, index) => {
      const offset = fourLetterOffset(index, 64);
      ctx.fillText(
        letter,
        index % 2 === 0 ? 16 + offset.x : 48 + offset.x,
        (index < 2 ? 16 : 48) + offset.y + 1,
      );
    });
  } else ctx.fillText(letters.join(""), 32, 33);
  return canvas.toDataURL("image/png");
}

/** Render only validated mark fields; SVG nodes come from the pinned icon table. */
function paintBrandingMark(element, branding, theme) {
  const mark = effectiveMark(branding, theme);
  const doc = element.ownerDocument;
  const size = element.getBoundingClientRect().width || 40;
  element.style.background = mark.background;
  element.style.color = mark.foreground;
  element.style.borderRadius =
    mark.shape === "circle"
      ? "50%"
      : mark.shape === "square"
        ? "0"
        : branding.design.radii.mark + "px";
  element.style.display = "inline-flex";
  element.style.alignItems = element.style.justifyContent = "center";
  element.style.overflow = "hidden";
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", "Знак платформы");
  const letters = () => {
    const grid = doc.createElement("span");
    grid.style.fontSize = markFontSize(mark.count, size) + "px";
    grid.style.fontWeight = "700";
    grid.style.lineHeight = "1";
    if (mark.count === 4) {
      Object.assign(grid.style, {
        display: "grid",
        width: "100%",
        height: "100%",
        gridTemplateColumns: "repeat(2,minmax(0,1fr))",
        gridTemplateRows: "repeat(2,minmax(0,1fr))",
      });
      markLetters(branding, mark)
        .slice(0, 4)
        .forEach((letter, index) => {
          const cell = doc.createElement("span");
          Object.assign(cell.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          });
          const glyph = doc.createElement("span");
          glyph.textContent = letter;
          const offset = fourLetterOffset(index, size);
          glyph.style.transform = `translate(${offset.x}px, ${offset.y}px)`;
          cell.appendChild(glyph);
          grid.appendChild(cell);
        });
    } else
      grid.textContent = markLetters(branding, mark)
        .slice(0, mark.count)
        .join("");
    element.replaceChildren(grid);
  };
  if (mark.kind === "image" && mark.image) {
    const image = doc.createElement("img");
    image.alt = "";
    Object.assign(image.style, {
      width: "100%",
      height: "100%",
      objectFit: mark.fit,
    });
    image.onerror = letters;
    image.src = mark.image.url;
    element.replaceChildren(image);
  } else if (mark.kind === "icon") {
    const parsed = new DOMParser().parseFromString(
      brandingIcons[mark.icon],
      "image/svg+xml",
    );
    const svg = doc.importNode(parsed.documentElement, true);
    svg.setAttribute("width", String(size * 0.6));
    svg.setAttribute("height", String(size * 0.6));
    element.replaceChildren(svg);
  } else letters();
}


/** @typedef { {version: 1, font_preset: 'system'|'inter'|'noto-sans', type_scale: 'standard'|'large', density: 'compact'|'standard'|'comfortable', radius: 'square'|'standard'|'rounded', colors?: Record<string,{primary:string,accent:string}>, radii?: Record<'control'|'menu'|'dialog'|'card'|'mark',number>, marks?: Record<string,any>, favicon?: any, documentation_url?: string, initial_theme?: 'dark'|'gray'|'light'} } BrandingDesign */
/** @typedef { {product_name: string, product_short_name: string, logo_url: string|null, favicon_url: string|null, support_url: string|null, primary_color: string, accent_color: string, surface_color: string|null, design?: BrandingDesign|null} } Branding */
/** @typedef { {revision: number, updated_at: string, branding: Branding} } BrandingDocument */

/** Versioned presentation choices. No executable CSS or arbitrary font URLs enter the document. */
const brandingPresets = {
  version: [1],
  font_preset: ["system", "inter", "noto-sans"],
  type_scale: ["standard", "large"],
  density: ["compact", "standard", "comfortable"],
  radius: ["square", "standard", "rounded"],
};
/** @type {Branding} */
const defaultBranding = {
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
const defaultDesign = {
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
function validBrandUrl(value) {
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
function normalizeBranding(payload) {
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
function resolveBrandingTokens(branding, theme = "dark") {
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
  // A brand changes surfaces slightly; essential text/status roles retain their contrast.
  const backgrounds = [
    colors.background,
    colors.surface,
    colors["surface-raised"],
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
    "--color-selection": mix(colors.surface, accent, 0.14),
    "--color-selection-foreground": readable(
      colors["text-primary"],
      [mix(colors.surface, accent, 0.14)],
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
function createBrandingRuntime(options) {
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

window.PdlcBranding={createBrandingRuntime,resolveBrandingTokens,normalizeBranding,defaultBranding,defaultDesign};
})();
