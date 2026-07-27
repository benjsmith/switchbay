import { toggleTheme } from "../theme";

/** Light/dark switcher. Lives in the BROWSER footer (bottom-left of
 *  the shell) to mirror curiosity-engine's wiki-view layout. */
export default function ThemeToggle() {
  return (
    <button
      type="button"
      className="sy-icon-btn"
      title="Toggle theme"
      aria-label="Toggle theme"
      onClick={() => toggleTheme()}
    >
      <svg className="sy-theme-icon-sun" viewBox="0 0 16 16" width="14" height="14">
        <circle cx="8" cy="8" r="3" fill="currentColor" />
        <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <line x1="8" y1="1.5" x2="8" y2="3" />
          <line x1="8" y1="13" x2="8" y2="14.5" />
          <line x1="1.5" y1="8" x2="3" y2="8" />
          <line x1="13" y1="8" x2="14.5" y2="8" />
          <line x1="3.4" y1="3.4" x2="4.5" y2="4.5" />
          <line x1="11.5" y1="11.5" x2="12.6" y2="12.6" />
          <line x1="3.4" y1="12.6" x2="4.5" y2="11.5" />
          <line x1="11.5" y1="4.5" x2="12.6" y2="3.4" />
        </g>
      </svg>
      <svg className="sy-theme-icon-moon" viewBox="0 0 16 16" width="14" height="14">
        <path
          d="M12.5 9.5 a 5 5 0 1 1 -6 -6 a 4 4 0 0 0 6 6 z"
          fill="currentColor"
        />
      </svg>
    </button>
  );
}
