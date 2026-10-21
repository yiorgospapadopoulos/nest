/** Where the transcript is: its scroll offset, the visible height and the content height. */
export interface ScrollMetrics {
  offset: number;
  viewport: number;
  content: number;
}

// How close to the end still counts as the bottom.
const THRESHOLD = 40;

export function isAtBottom({ offset, viewport, content }: ScrollMetrics): boolean {
  return offset + viewport >= content - THRESHOLD;
}

/** Exactly at the end, where shrinking content or a taller view pins the offset. */
function isAtEnd({ offset, viewport, content }: ScrollMetrics): boolean {
  return offset + viewport >= content - 1;
}

/**
 * Whether the transcript follows new content, as the Mac's ScrollFollow (D099): only the
 * user's own scrolling starts or stops it. Any move up stops it and only a move down into
 * the bottom zone, or Jump to latest, resumes it. Content that grows or a view that
 * resizes (the keyboard) never does.
 */
export class ScrollFollow {
  following = true;
  // Scrolling to the latest after Jump to latest, until the bottom is reached.
  private jumping = false;
  private last: ScrollMetrics | null = null;

  /** Jump to latest is offered while it does not follow (a phone has no scroll bar). */
  get showsJump(): boolean {
    return !this.following;
  }

  /** Reads a scroll; returns true when the view should scroll to the bottom. */
  update(metrics: ScrollMetrics): boolean {
    const last = this.last;
    this.last = metrics;
    const bottom = isAtBottom(metrics);
    if (bottom) this.jumping = false;
    if (last?.viewport !== metrics.viewport || this.jumping) {
      return this.following && !bottom;
    }
    // Any move up stops following, however small; only a move pinned to the end is not
    // the user's.
    if (metrics.offset < last.offset && !isAtEnd(metrics)) {
      this.following = false;
      return false;
    }
    if (metrics.offset > last.offset && bottom) {
      this.following = true;
      return false;
    }
    return this.following && !bottom;
  }

  /** New content arrived; returns true when the view should scroll to the bottom. */
  contentArrived(): boolean {
    return this.following;
  }

  /** The view went to an earlier item on purpose, such as a search hit. */
  hold(): void {
    this.following = false;
    this.jumping = false;
  }

  jumpToLatest(): void {
    this.following = true;
    // Already at the bottom, no scroll follows to end the jump.
    this.jumping = this.last === null || !isAtBottom(this.last);
  }
}
