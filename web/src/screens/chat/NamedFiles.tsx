import type { ReactNode } from "react";
import { useNamedFiles } from "../../ui/namedFiles.ts";
import { OpenFileContext, ReadFileContext } from "../../ui/openFile.ts";
import { FileSheet } from "./FileSheet.tsx";

/** Lets a chat's messages open the files they name in the viewer, on the phone (B144). */
export function NamedFiles({ session, children }: { session: string; children: ReactNode }) {
  const named = useNamedFiles(session);
  return (
    <OpenFileContext value={named.open}>
      <ReadFileContext value={named.read}>
        {children}
        {named.viewing !== null && <FileSheet source={named.viewing} onClose={named.close} />}
      </ReadFileContext>
    </OpenFileContext>
  );
}
