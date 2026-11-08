import { useFileView, type FileSource } from "../../ui/useFileView.tsx";
import { useBridge } from "../context.ts";
import { Glyph } from "./glyphs.tsx";
import { saveBlob } from "./saveBlob.ts";
import { Sheet } from "./Sheet.tsx";

interface Props {
  source: FileSource;
  onClose: () => void;
  // For a file of a chat on this computer: opens it in the text editor, as before B144.
  onEditor?: (() => void) | undefined;
}

/** A file in the viewer, large over the window (B144, option A of its mockups). */
export function FileSheet({ source, onClose, onEditor }: Props) {
  const bridge = useBridge();
  const view = useFileView(source);
  const { blob } = view;
  return (
    <Sheet title={view.title} onClose={onClose} large bare>
      <div className="dc-sheet-h fv-h">
        <h2>{view.title}</h2>
        {view.meta !== null && <span className="fv-meta">{view.meta}</span>}
        {onEditor !== undefined && (
          <button className="dk-btn" onClick={onEditor}>
            Open in editor
          </button>
        )}
        <button
          className="dk-btn"
          disabled={blob === null}
          onClick={() => {
            if (blob !== null) void saveBlob(bridge, view.title, blob);
          }}
        >
          Save
        </button>
        <button
          className="dk-btn k-plain icon"
          aria-label={`Close ${view.title}`}
          onClick={onClose}
        >
          <Glyph name="close" size={10} />
        </button>
      </div>
      <div className="fv-b">{view.body}</div>
    </Sheet>
  );
}
