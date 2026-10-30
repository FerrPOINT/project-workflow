/** The document owns the font, including marks rendered outside its token scope.
 * @param {'system'|'inter'|'noto-sans'} [preset]
 * @returns {string}
 */
export function brandingFontFamily(preset = "system") {
  return {
    system:
      'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    inter: '"PDLC Inter", system-ui, sans-serif',
    "noto-sans": '"PDLC Noto Sans", system-ui, sans-serif',
  }[preset];
}
