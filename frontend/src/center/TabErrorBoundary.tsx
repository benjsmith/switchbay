import { Component, type ReactNode } from "react";

/**
 * Generic error boundary around whichever tab widget is mounted in the
 * center strip. A render throw in ANY tab (a malformed Vega spec, a
 * DuckDB-wasm state error, the forked CE graph code, …) used to blank
 * the entire app to white — taking the tab strip, rail, and sidebar
 * down with it, recoverable only by a full reload. This keeps the
 * chrome alive: the crashed tab shows a recovery panel, everything
 * else stays usable.
 *
 * Keyed by tab id at the call site, so switching to another tab (or
 * back) mounts a fresh boundary and clears a crashed state
 * automatically — no manual reset needed to move on.
 */

type Props = { children: ReactNode; label?: string };
type State = { error: Error | null; resetTick: number };

export default class TabErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetTick: 0 };

  static getDerivedStateFromError(error: Error): State {
    return { error, resetTick: 0 };
  }

  componentDidCatch(error: Error, info: unknown): void {
    console.error(`[tab${this.props.label ? `:${this.props.label}` : ""}] crashed:`, error, info);
  }

  reset = () => {
    this.setState((s) => ({ error: null, resetTick: s.resetTick + 1 }));
  };

  render() {
    if (!this.state.error) {
      return (
        <div
          key={this.state.resetTick}
          style={{
            height: "100%",
            width: "100%",
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {this.props.children}
        </div>
      );
    }
    return (
      <div className="sy-vega-empty">
        <h2>This tab crashed</h2>
        <p>
          Something inside {this.props.label ? <code>{this.props.label}</code> : "this view"}{" "}
          threw an error. The rest of Switch Bay is intact — switch tabs, or
          reset this view below.
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
