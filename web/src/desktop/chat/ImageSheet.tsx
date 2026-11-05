import { useEffect } from "react";
import { download } from "../../screens/artifacts/files.ts";
import type { SentFile } from "../../transcript/build.ts";
import { SentFiles, type ImageViewer } from "../../ui/SentFiles.tsx";
import type { Bridge } from "../bridge.ts";
import { useBridge } from "../context.ts";
import { useRows } from "./rowsContext.ts";
import { Sheet } from "./Sheet.tsx";

type Viewer = Pick<ImageViewer, "url" | "onClose"> & Partial<Pick<ImageViewer, "alt">>;

/** An image full size, as the Mac's ImageSheet: fitted inside the window's margins. */
export function ImageSheet({ url, alt = "Image from the tool", onClose }: Viewer) {
  return (
    <Sheet title="Image" onClose={onClose} large>
      <div className="dc-imgfull">
        <img src={url} alt={alt} />
      </div>
    </Sheet>
  );
}

async function saved(bridge: Bridge, name: string, blob: Blob): Promise<void> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  await bridge.saveFile(name, { base64: btoa(binary) });
}

/** In a pane of the Mac app the image opens over the window there. */
function AppImage({ id, onClose }: ImageViewer) {
  const { host } = useRows();
  useEffect(() => {
    if (id !== undefined) host?.openImage(id);
    onClose();
  }, [host, id, onClose]);
  return null;
}

/** A message's sent images and files, in the app's window. */
export function Sent({ files }: { files: SentFile[] }) {
  const bridge = useBridge();
  const { host } = useRows();
  const save = (name: string, blob: Blob) => {
    if (bridge.native) void saved(bridge, name, blob);
    else download(name, blob);
  };
  return <SentFiles files={files} Viewer={host === null ? ImageSheet : AppImage} save={save} />;
}
