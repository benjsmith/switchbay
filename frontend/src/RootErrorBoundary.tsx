import { Component, type ReactNode } from "react";

/**
 * Last-resort boundary around the whole App. The per-tab
 * TabErrorBoundary catches widget crashes; this catches a throw in the
 * shared shell (layout, rail, workspace switch) that would otherwise
 * leave a blank white page with no way back. It offers a reload rather
 * than a subtree reset, because a shell-level crash usually needs a
 * fresh mount.
 */

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class RootErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown): void {
    console.error("[app] crashed:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        style={{
          display: "grid", placeItems: "center", height: "100vh",
          fontFamily: "system-ui", padding: 24, textAlign: "center",
        }}
      >
        <div style={{ maxWidth: 520 }}>
          <h2>Switch Bay hit an error</h2>
          <p style={{ opacity: 0.8 }}>
            The interface crashed. Your work is safe on the daemon — reloading
            reconnects to it.
          </p>
          <pre
            style={{
              whiteSpace: "pre-wrap", textAlign: "left", marginTop: 12,
              padding: 12, borderRadius: 8, background: "rgba(127,127,127,0.12)",
              fontSize: 12,
            }}
          >
            {this.state.error.message}
          </pre>
          <button
            type="button"
            style={{ marginTop: 16, padding: "8px 16px", borderRadius: 8, cursor: "pointer" }}
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
