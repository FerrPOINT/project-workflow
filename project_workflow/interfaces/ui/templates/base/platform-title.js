export const DEFAULT_PLATFORM_NAME = "PDLC";
/** @param {string} serviceLabel @param { {product_short_name?: string}} [branding] */
export function platformTitle(serviceLabel, branding) {
  const name =
    (typeof branding?.product_short_name === "string" &&
      branding.product_short_name.trim()) ||
    DEFAULT_PLATFORM_NAME;
  return `${serviceLabel} — ${name}`;
}
