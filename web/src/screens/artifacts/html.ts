// What an artifact's page may do in its frame (B82): run inline scripts and scripts from the
// pinned CDN hosts, use inline styles and Google Fonts, show data: and blob: images, and
// reach nothing else. The Mac uses the same string.
export const ARTIFACT_CSP =
  "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/ https://unpkg.com https://cdn.tailwindcss.com https://code.jquery.com; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; worker-src 'none'";

const META = `<meta http-equiv="Content-Security-Policy" content="${ARTIFACT_CSP}">`;
const DOCTYPE = /^\s*<!doctype[^>]*>/i;

/**
 * The document with the policy as the first child of its head. The meta goes before any of
 * the document's own markup (after its doctype, which must stay first): the HTML parser
 * then opens the html and head elements around it, merges the document's own <html> and
 * <head> into them, and so applies the policy before anything else loads. Placing it by
 * searching for "<head>" instead could land it inside a comment or a script's text.
 */
export function withCsp(html: string): string {
  const doctype = DOCTYPE.exec(html)?.[0] ?? "";
  return `${doctype}${META}${html.slice(doctype.length)}`;
}
