/**
 * Images get ready before they upload, like Claude Code: HEIC turns into JPEG where the
 * browser can decode it (Safari can), and an image larger than 2000 px on its long edge is
 * scaled down. Anything the browser cannot decode or encode goes as it is.
 */

export const MAX_EDGE = 2000;
const JPEG_QUALITY = 0.9;
const HEIC = /\.hei[cf]$/i;
// Scaling would drop a GIF's animation; an SVG has no pixels to scale.
const AS_IS = new Set(["image/gif", "image/svg+xml"]);

export async function prepareImage(file: File): Promise<File> {
  const heic = /^image\/hei[cf]/i.test(file.type) || HEIC.test(file.name);
  if (!heic && (!file.type.startsWith("image/") || AS_IS.has(file.type))) return file;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return file;
  }
  const { width, height } = bitmap;
  const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
  if (!heic && scale === 1) {
    bitmap.close();
    return file;
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  if (context === null) return file;
  // A screenshot stays sharp as PNG; photos and HEIC become JPEG.
  const png = file.type === "image/png";
  const type = png ? "image/png" : "image/jpeg";
  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob(resolve, type, JPEG_QUALITY);
  });
  if (blob === null) return file;
  return new File([blob], renamed(file.name, png ? "png" : "jpg"), { type });
}

function renamed(name: string, extension: string): string {
  const dot = name.lastIndexOf(".");
  return `${dot > 0 ? name.slice(0, dot) : name}.${extension}`;
}
