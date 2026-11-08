import { useFileView, type FileSource } from "../../ui/useFileView.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { download } from "../artifacts/files.ts";

/** A file in the viewer, full screen on the phone (B144). */
export function FileSheet({ source, onClose }: { source: FileSource; onClose: () => void }) {
  const view = useFileView(source);
  const { blob } = view;
  return (
    <Sheet
      title={view.title}
      full
      onClose={onClose}
      leading={
        <button
          className="done"
          disabled={blob === null}
          onClick={() => {
            if (blob !== null) download(view.title, blob);
          }}
        >
          Save
        </button>
      }
    >
      {view.meta !== null && <p className="fv-meta">{view.meta}</p>}
      <div className="fv-b">{view.body}</div>
    </Sheet>
  );
}
