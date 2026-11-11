import type { ArtifactContent } from "../../api/types.ts";
import { download, fileBlob } from "../../screens/artifacts/files.ts";
import type { Bridge } from "../bridge.ts";
import { fileName, savedText } from "./text.ts";

/**
 * Save as file: the version as written (HTML without the injected policy), where the user
 * picks in the system's save dialog, as the Mac's saveArtifact; a download in a browser.
 * Resolves to where it was saved, null for a download or a cancelled dialog.
 */
export async function saveAs(content: ArtifactContent, bridge: Bridge): Promise<string | null> {
  const name = fileName(content.title, content.kind);
  if (!bridge.native) {
    download(name, fileBlob(content.kind, savedText(content)));
    return null;
  }
  return bridge.saveFile(name, { text: savedText(content) });
}
