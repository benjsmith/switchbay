import type { ReactNode } from "react";

type Props = {
  topbar: ReactNode;
  sidebar: ReactNode;
  center: ReactNode;
  rail: ReactNode;
};

/** Three-column shell with a top bar. Grid layout defined in index.css. */
export default function Shell({ topbar, sidebar, center, rail }: Props) {
  return (
    <div className="sy-shell">
      <header className="sy-topbar">{topbar}</header>
      <aside className="sy-side">{sidebar}</aside>
      <section className="sy-center">{center}</section>
      <aside className="sy-rail">{rail}</aside>
    </div>
  );
}
