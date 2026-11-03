// What a pane's header and composer show at the pane's width, ported from NestKit's
// PaneFit.swift: the header drops the pull request chip first; the composer shortens where
// the chat works to its icon, then hides the context, then uses short selector labels
// ("Sonnet", "Med", "Edits"). Attach, dictation and send always stay, and no label is
// ever cut to a stub.

export interface PaneFit {
  showsPullRequest: boolean;
  // The branch or worktree name beside its icon in the composer.
  showsPlaceName: boolean;
  showsContext: boolean;
  // Short selector labels.
  compact: boolean;
}

export function paneFit(width: number): PaneFit {
  return {
    showsPullRequest: width >= 420,
    showsPlaceName: width >= 560,
    showsContext: width >= 360,
    compact: width < 380,
  };
}

/** The pane's data attributes, which desktop.css reads. */
export function fitAttributes(fit: PaneFit): Record<string, string | undefined> {
  return {
    "data-fit-pr": fit.showsPullRequest ? undefined : "hidden",
    "data-fit-place": fit.showsPlaceName ? undefined : "icon",
    "data-fit-context": fit.showsContext ? undefined : "hidden",
    "data-fit-compact": fit.compact ? "" : undefined,
  };
}
