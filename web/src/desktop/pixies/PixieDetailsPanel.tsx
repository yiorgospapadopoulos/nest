import { useState } from "react";
import type { Pixie } from "../../api/types.ts";
import { ActivityPage } from "./ActivityPage.tsx";
import { FilePage } from "./FilePage.tsx";
import { HabitEditor, HabitHistory, HabitsPage } from "./HabitsPage.tsx";
import { MemoryPage } from "./MemoryPage.tsx";
import { backOf, DETAILS, shownPage, type PanelState, type PixiePage } from "./panel.ts";
import { PixieDetails } from "./PixieDetails.tsx";
import "./details.css";

/**
 * The Pixies tab's right panel for the focused pixie (PixiesView.swift, 320 wide on the
 * side surface): its details, or Soul, Memory, a note, Habits or Activity opened from them
 * in place, each with a way back. Another pixie's focus brings the details back.
 */
export function PixieDetailsPanel({ pixie }: { pixie: Pixie }) {
  const [state, setState] = useState<PanelState>({ pixie: pixie.id, page: DETAILS });
  const page = shownPage(state, pixie.id);
  const open = (next: PixiePage) => {
    setState({ pixie: pixie.id, page: next });
  };
  return (
    <aside className="pd-panel" aria-label={`${pixie.name} details`}>
      <Shown key={`${pixie.id}/${JSON.stringify(page)}`} pixie={pixie} page={page} open={open} />
    </aside>
  );
}

function Shown({
  pixie,
  page,
  open,
}: {
  pixie: Pixie;
  page: PixiePage;
  open: (page: PixiePage) => void;
}) {
  switch (page.page) {
    case "details":
      return <PixieDetails pixie={pixie} open={open} />;
    case "soul":
    case "note": {
      const back = backOf(page) ?? { page: DETAILS, label: "Details" };
      return (
        <FilePage
          pixie={pixie}
          name={page.page === "soul" ? "soul" : `notes/${page.note}`}
          title={page.page === "soul" ? "Soul" : page.note}
          back={back.label}
          close={() => {
            open(back.page);
          }}
        />
      );
    }
    case "memory":
      return <MemoryPage pixie={pixie} open={open} />;
    case "activity":
      return <ActivityPage pixie={pixie} open={open} />;
    case "habits":
      return <HabitsPage pixie={pixie} open={open} />;
    case "habit":
      return <HabitEditor pixie={pixie} habitId={page.habit} open={open} />;
    case "history":
      return <HabitHistory pixie={pixie} habitId={page.habit} open={open} />;
  }
}
