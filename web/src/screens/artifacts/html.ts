// What an HTML artifact may do in its frame (contract section 6): run its own inline
// scripts and styles, show data: images, and load nothing else.
export const ARTIFACT_CSP =
  "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'";

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
