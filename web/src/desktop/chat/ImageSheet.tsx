import { Sheet } from "./Sheet.tsx";

/** An image full size, as the Mac's ImageSheet: fitted inside the window's margins. */
export function ImageSheet({ url, onClose }: { url: string; onClose: () => void }) {
  return (
    <Sheet title="Image" onClose={onClose} large>
      <div className="dc-imgfull">
        <img src={url} alt="Image from the tool" />
      </div>
    </Sheet>
  );
}
