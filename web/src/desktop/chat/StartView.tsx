import { useState } from "react";
import type { Session } from "../../api/types.ts";
import { age, question, questions, startLists } from "../../screens/chat/start.ts";
import { useStore } from "../../store/context.ts";
import { projectName, repoNamed } from "../../store/general.ts";
import { shownTitle } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { ProjectMark } from "../shell/bits.tsx";
import { Composer } from "./Composer.tsx";

interface Props {
  repo: string;
  onOpen: (id: string) => void;
  onCreated: (session: Session) => void;
}

/**
 * The empty workspace, as the Mac's StartSession (B90 design I): the project, a question
 * and the composer docked at the bottom where a chat's composer sits; beside them, while
 * the workspace is wide enough, what waits on the user and the latest chats.
 */
export function StartView({ repo: name, onOpen, onCreated }: Props) {
  const { state } = useStore();
  const repo = repoNamed(state.repos, name);
  // Taken when the view appears and kept while it stays.
  const [asked] = useState(() => questions.next());
  const { waiting, recent } = startLists(state, name);
  const now = new Date();
  const title = projectName(name);
  const column = waiting.length > 0 || recent.length > 0;
  return (
    <section className="dk-startv" aria-label={`Start a chat in ${title}`}>
      <div className="dk-startv-in">
        <div className="dk-startv-main">
          <div className="dk-startv-who">
            <ProjectMark name={name} repo={repo} />
            {title}
          </div>
          <h1 className="dk-startv-q">{question(asked, title)}</h1>
          <Composer target={{ kind: "start", repo: name, onCreated }} />
        </div>
        {column && (
          <aside className="dk-startv-col" aria-label="Waiting and recent">
            {waiting.length > 0 && (
              <>
                <h3 className="dk-startv-lbl">Waiting on you · {waiting.length}</h3>
                {waiting.map((item) => (
                  <button
                    key={item.id}
                    className="dk-startv-row"
                    onClick={() => {
                      onOpen(item.chat);
                    }}
                  >
                    <Dot tone={item.tone} />
                    <span className="dk-startv-t">
                      <span>{item.title}</span>
                      <span className="dk-startv-m">{item.line}</span>
                    </span>
                  </button>
                ))}
              </>
            )}
            {recent.length > 0 && (
              <>
                <h3 className="dk-startv-lbl">Recent chats</h3>
                {recent.map((chat) => (
                  <button
                    key={chat.id}
                    className="dk-startv-row recent"
                    onClick={() => {
                      onOpen(chat.id);
                    }}
                  >
                    <span className="dk-startv-t">
                      <span>{shownTitle(chat)}</span>
                    </span>
                    <span className="dk-startv-a">{age(chat.updated_at, now)}</span>
                  </button>
                ))}
              </>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}
