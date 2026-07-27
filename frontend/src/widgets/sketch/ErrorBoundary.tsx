import { Component, type ReactNode } from "react";

/**
 * Local error boundary for the Sketch tab. A crash inside Excalidraw
 * or drawio shouldn't take the whole UI down to a blank page; we
 * trap and render a recovery panel instead.
 *
 * The user can click "Reset" to remount the children. If the crash
 * is deterministic (same scene, same code path) the reset will
 * trigger again — but at least the chrome is intact and the user
 * can navigate away to other tabs.
 */

type Props = { children: ReactNode };
type State = { error: Error | null; resetTick: number };

export default class SketchErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetTick: 0 };

  static getDerivedStateFromError(error: Error): State {
    return { error, resetTick: 0 };
  }

  componentDidCatch(error: Error, info: unknown): void {
    // Surface in console so DevTools can copy the stack. Doing this
    // in the boundary rather than the React inner-trace because the
    // browser console version is actionable.
    console.error("[SketchTab] crashed:", error, info);
  }

  reset = () => {
    // Bump the key on the children wrapper so React fully unmounts +
    // remounts the SketchTab subtree. Without this, clearing
    // `error` to null re-renders the same children which trigger
    // the same crash (Reset button felt broken). The remount also
    // wipes any in-memory hooks state that might be holding onto
    // the bad scene.
    this.setState((s) => ({ error: null, resetTick: s.resetTick + 1 }));
  };

  render() {
    if (!this.state.error) {
      return (
        <div key={this.state.resetTick} style={{ height: "100%", width: "100%" }}>
          {this.props.children}
        </div>
      );
    }
    return (
      <div className="sy-vega-empty">
        <h2>Sketch tab crashed</h2>
        <p>
          Something inside the canvas threw an error. The chrome is
          intact — you can switch tabs or reset this view below.
        </p>
        <pre className="sy-vega-err" style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
          {this.state.error.message}
        </pre>
        <button
          type="button"
          className="sy-vega-toolbar-btn"
          style={{ marginTop: 16 }}
          onClick={this.reset}
        >
          Reset
        </button>
      </div>
    );
  }
}
