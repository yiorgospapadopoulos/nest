import { useEffect } from "react";
import type { SentFile } from "../../transcript/build.ts";
import { SentFiles, type ImageViewer } from "../../ui/SentFiles.tsx";
import { FileSheet } from "./FileSheet.tsx";
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
  const { host } = useRows();
  return (
    <SentFiles
      files={files}
      Viewer={host === null ? ImageSheet : AppImage}
      FileViewer={FileSheet}
    />
  );
}
