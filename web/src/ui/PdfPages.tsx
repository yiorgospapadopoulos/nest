import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
} from "pdfjs-dist/legacy/build/pdf.mjs";
import worker from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

// Mozilla's pdf.js, loaded only when a PDF opens (B144): the Linux app and the iPhone show
// no PDF in a page on their own. The legacy build runs on older WebKit too.
GlobalWorkerOptions.workerSrc = worker;

interface Props {
  data: Blob;
  // The page most in view and the count, for the viewer's header.
  onPage: (page: number, pages: number) => void;
  onFailed: () => void;
}

export default function PdfPages({ data, onPage, onFailed }: Props) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const report = useRef({ onPage, onFailed });
  useEffect(() => {
    report.current = { onPage, onFailed };
  });

  useEffect(() => {
    let live = true;
    let task: ReturnType<typeof getDocument> | null = null;
    void data
      .arrayBuffer()
      .then((bytes) => {
        task = getDocument({ data: new Uint8Array(bytes) });
        return task.promise;
      })
      .then((doc) => {
        if (!live) return;
        setPdf(doc);
        report.current.onPage(1, doc.numPages);
      })
      .catch(() => {
        if (live) report.current.onFailed();
      });
    return () => {
      live = false;
      void task?.destroy();
    };
  }, [data]);

  if (pdf === null) return null;
  const pages = Array.from({ length: pdf.numPages }, (_, index) => index + 1);
  return (
    <div className="fv-pdf">
      {pages.map((number) => (
        <Page
          key={number}
          pdf={pdf}
          number={number}
          onSeen={() => {
            report.current.onPage(number, pdf.numPages);
          }}
        />
      ))}
    </div>
  );
}

/** One page, drawn when it first comes near the view, at the screen's own sharpness. */
function Page({
  pdf,
  number,
  onSeen,
}: {
  pdf: PDFDocumentProxy;
  number: number;
  onSeen: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  const seen = useRef(onSeen);
  useEffect(() => {
    seen.current = onSeen;
  });

  useEffect(() => {
    const element = canvas.current;
    if (element === null) return;
    let drawn = false;
    let task: { cancel: () => void } | null = null;
    const draw = async () => {
      drawn = true;
      const page = await pdf.getPage(number);
      const width = element.parentElement?.clientWidth ?? 600;
      const base = page.getViewport({ scale: 1 });
      const scale = (width / base.width) * window.devicePixelRatio;
      const viewport = page.getViewport({ scale });
      element.width = Math.floor(viewport.width);
      element.height = Math.floor(viewport.height);
      setRatio(base.height / base.width);
      const render = page.render({ canvas: element, viewport });
      task = render;
      await render.promise.catch(() => undefined);
    };
    const near = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting === true && !drawn) void draw();
      },
      { rootMargin: "800px 0px" },
    );
    const middle = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting === true) seen.current();
      },
      { rootMargin: "-50% 0px -50% 0px" },
    );
    near.observe(element);
    middle.observe(element);
    return () => {
      near.disconnect();
      middle.disconnect();
      task?.cancel();
    };
  }, [pdf, number]);

  return (
    <canvas
      ref={canvas}
      className="fv-page"
      style={{ aspectRatio: ratio === null ? "1 / 1.414" : `1 / ${String(ratio)}` }}
      aria-label={`Page ${String(number)}`}
      role="img"
    />
  );
}
