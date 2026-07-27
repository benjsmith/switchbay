/** Top-right settings button. Distinct sliders icon (not the cog used
 *  in the graph tab's physics panel) so the two never get confused. */

type Props = {
  onClick: () => void;
};

export default function SettingsButton({ onClick }: Props) {
  return (
    <button
      type="button"
      className="sy-icon-btn"
      title="Settings"
      aria-label="Settings"
      data-tour="settings"
      onClick={onClick}
    >
      {/* Three horizontal sliders, each with a knob at a different
          position. Reads as "settings" without colliding with CE's
          physics-cog icon. */}
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <line x1="2" y1="4" x2="14" y2="4" />
        <line x1="2" y1="8" x2="14" y2="8" />
        <line x1="2" y1="12" x2="14" y2="12" />
        <circle cx="11" cy="4" r="1.7" fill="var(--bg-soft)" />
        <circle cx="5"  cy="8" r="1.7" fill="var(--bg-soft)" />
        <circle cx="10" cy="12" r="1.7" fill="var(--bg-soft)" />
      </svg>
    </button>
  );
}
