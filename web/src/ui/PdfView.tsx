import { lazy, Suspense, type ComponentProps } from "react";

// pdf.js loads only when a PDF opens.
const PdfPages = lazy(() => import("./PdfPages.tsx"));

export function PdfView(props: ComponentProps<typeof PdfPages>) {
  return (
    <Suspense fallback={<p className="fv-empty">Loading</p>}>
      <PdfPages {...props} />
    </Suspense>
  );
}
