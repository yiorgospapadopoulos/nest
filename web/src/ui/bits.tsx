import { initials } from "../format.ts";
import type { Tone } from "../store/selectors.ts";

export function Dot({ tone }: { tone: Tone }) {
  return <span className={`dot s-${tone}`} aria-hidden="true" />;
}

export function Pill({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`sp s-${tone}`}>
      <Dot tone={tone} />
      <span>{label}</span>
    </span>
  );
}

// A stable color per project name, from the four project tints of the design.
function tint(name: string): number {
  let sum = 0;
  for (const char of name) sum += char.charCodeAt(0);
  return sum % 4;
}

export function ProjectIcon({ name }: { name: string }) {
  return (
    <span className={`pico pi-${String(tint(name))}`} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function DiffStats({
  additions,
  deletions,
  files,
}: {
  additions: number;
  deletions: number;
  files: number;
}) {
  // Five cells split like GitHub's: green for additions, red for deletions, grey for none.
  const green = Math.round((additions / Math.max(1, additions + deletions)) * 5);
  return (
    <>
      <span className="ds">
        <span className="a">+{additions}</span> <span className="d">-{deletions}</span>{" "}
        <span className="f">
          {files} {files === 1 ? "file" : "files"}
        </span>
      </span>
      <span className="dbar" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <i key={i} className={additions + deletions === 0 ? "" : i < green ? "a" : "d"} />
        ))}
      </span>
    </>
  );
}
