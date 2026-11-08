import { download } from "../../screens/artifacts/files.ts";
import type { Bridge } from "../bridge.ts";

/** Hands a file to the user: the save dialog in the app, a download in a browser. */
export async function saveBlob(bridge: Bridge, name: string, blob: Blob): Promise<void> {
  if (!bridge.native) {
    download(name, blob);
    return;
  }
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  await bridge.saveFile(name, { base64: btoa(binary) });
}
