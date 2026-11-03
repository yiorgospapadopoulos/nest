// What a chat pane's header and composer show at the pane's width, ported from NestKit's
// PaneFit.swift: the header keeps the chat's name first and drops the run's extra ports,
// then the pull request chip, then shortens who started the chat; the composer shortens
// where the chat works to its icon, shortens then hides the context, and uses short
// selector labels. Attach and send always stay.
import { createContext, use } from "react";
import type { ContextUsage, Effort, PermissionMode } from "../../api/types.ts";

export type ContextStyle = "full" | "percent" | "hidden";

export interface ChatFit {
  // Who started a chat in full, in the header.
  showsHeaderDetails: boolean;
  showsPlaceName: boolean;
  showsPullRequest: boolean;
  // A run's port chips beyond the first (B108).
  showsAllPorts: boolean;
  context: ContextStyle;
  compact: boolean;
  // A pixie pane's Details button keeps its word.
  showsDetailsLabel: boolean;
}

export function chatFit(width: number): ChatFit {
  return {
    showsPullRequest: width >= 420,
    showsAllPorts: width >= 400,
    showsHeaderDetails: width >= 360,
    showsPlaceName: width >= 560,
    context: width >= 460 ? "full" : width >= 360 ? "percent" : "hidden",
    compact: width < 380,
    showsDetailsLabel: width >= 480,
  };
}

/** "context 41%", "41%" or nothing, as the pane's width allows. */
export function contextLabel(style: ContextStyle, context: ContextUsage): string | null {
  const percent = String(Math.round(context.percent));
  if (style === "full") return `context ${percent}%`;
  return style === "percent" ? `${percent}%` : null;
}

// Above this share the context meter turns amber.
export const HIGH_CONTEXT = 80;

/** A model's name without its version: "Sonnet" for "Sonnet 5.5". */
export function shortModel(label: string): string {
  return label.split(" ")[0] ?? label;
}

export function shortEffort(effort: Effort, label: string): string {
  if (effort === "medium") return "Med";
  return effort === "xhigh" ? "X-high" : label;
}

export function shortPermission(mode: PermissionMode, label: string): string {
  return mode === "acceptEdits" ? "Edits" : label;
}

const WIDE = chatFit(1000);

/** The fit of the pane a chat shows in; a chat outside a pane (a test) shows everything. */
export const FitContext = createContext<ChatFit>(WIDE);

export function useFit(): ChatFit {
  return use(FitContext);
}
