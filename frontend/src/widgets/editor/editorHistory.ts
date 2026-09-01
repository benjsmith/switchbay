/**
 * Where the Editor has been.
 *
 * Lives outside the component so a tab switch (which unmounts the
 * Editor) doesn't erase the trail — following a wikilink, glancing at
 * the Graph and coming back should still offer Back.
 *
 * Only page-to-page moves are recorded, and only the last few: this is
 * a "go back one hop" affordance, not a browser history.
 */

export type EditorVisit = { id: string; path: string };

const MAX_DEPTH = 40;
let stack: EditorVisit[] = [];
/** Set while Back is navigating, so the resulting selection change is
 *  not pushed straight back onto the stack. */
let rewinding = false;

export function noteEditorVisit(next: EditorVisit | null): void {
  if (rewinding) {
    rewinding = false;
    return;
  }
  if (!next?.id) return;
  const top = stack[stack.length - 1];
  if (top && top.id === next.id) return;
  stack.push(next);
  if (stack.length > MAX_DEPTH) stack = stack.slice(-MAX_DEPTH);
}

/** The visit to return to, or null when there is nowhere to go back to.
 *  Pops the current page as well — Back means "the one before this". */
export function popEditorHistory(): EditorVisit | null {
  if (stack.length < 2) return null;
  stack.pop();
  const prev = stack[stack.length - 1] ?? null;
  if (prev) rewinding = true;
  return prev;
}

export function canGoBack(): boolean {
  return stack.length > 1;
}

/** A workspace switch invalidates every path on the stack. */
export function clearEditorHistory(): void {
  stack = [];
  rewinding = false;
}
