import { isHex } from "./branding-colors.js";
import { brandingIcons } from "./branding-icons.js";
import { DEFAULT_PLATFORM_NAME } from "./platform-title.js";
/** @template T @param { {design:{marks:{common:T,light:T|null,dark:T|null} }} } document @param {string} theme @returns {T} */
export function effectiveMark(document, theme) {
  return (
    document.design.marks[theme === "light" ? "light" : "dark"] ??
    document.design.marks.common
  );
}
/** @param {string} value @returns {string[]} */
export function graphemes(value) {
  return Array.from(
    new Intl.Segmenter("ru", { granularity: "grapheme" }).segment(value),
    (part) => part.segment,
  );
}
/** @param { {letters:string,count:number} } mark @returns {boolean} */
export function validMonogram(mark) {
  const letters = graphemes(mark.letters);
  return (
    new TextEncoder().encode(mark.letters).length <= 128 &&
    letters.length === mark.count &&
    letters.every(
      (letter) =>
        !/[\s\p{Cc}]/u.test(letter) && !/^[\p{M}\p{C}]+$/u.test(letter),
    )
  );
}
/** @param { {product_short_name:string} } document @param { {kind:string,letters:string,count:number} } mark @returns {string[]} */
export function markLetters(document, mark) {
  return graphemes(
    mark.kind === "letters" && validMonogram(mark)
      ? mark.letters
      : (document.product_short_name || DEFAULT_PLATFORM_NAME)
          .toUpperCase()
          .padEnd(4, DEFAULT_PLATFORM_NAME[0]),
  );
}
/** @param { {count:number} } mark @param {boolean} compact @param {boolean} failed @returns {number} */
export function markCount(mark, compact, failed) {
  return failed || (compact && mark.count === 4) ? 1 : mark.count;
}
/** @param {number} count @param {number} size @returns {number} */
export function markFontSize(count, size) {
  return size * (count === 4 ? 0.36 : count === 2 ? 0.38 : 0.56);
}
/** @param {number} index @param {number} size */
export function fourLetterOffset(index, size) {
  return {
    x: size * 0.04 * (index % 2 === 0 ? 1 : -1),
    y: size * 0.04 * (index < 2 ? 1 : -1),
  };
}
export async function brandingFavicon(brand, theme) {
  const mark = effectiveMark(brand, theme);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const validColors = isHex(mark.foreground) && isHex(mark.background);
  const foreground = validColors ? mark.foreground : "#ffffff";
  const radius =
    mark.shape === "circle"
      ? 32
      : mark.shape === "square"
        ? 0
        : brand.design.radii.mark;
  ctx.beginPath();
  ctx.roundRect(0, 0, 64, 64, radius);
  ctx.clip();
  ctx.fillStyle = validColors ? mark.background : "#2563eb";
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
  ctx.font = `700 ${markFontSize(count, 64)}px sans-serif`;
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
export function paintBrandingMark(element, branding, theme) {
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
  const letters = (failed = false) => {
    const count = markCount(mark, false, failed);
    const grid = doc.createElement("span");
    grid.style.fontSize = markFontSize(count, size) + "px";
    grid.style.fontWeight = "700";
    grid.style.lineHeight = "1";
    if (count === 4) {
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
      grid.textContent = markLetters(branding, mark).slice(0, count).join("");
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
    image.onerror = () => letters(true);
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
