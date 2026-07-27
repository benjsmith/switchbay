/** Top-bar help button — a circled question mark that opens the
 *  "how Switch Bay works" modal. Sits next to Settings; reuses the
 *  same .sy-icon-btn chrome so the top-right cluster stays uniform. */

type Props = {
  onClick: () => void;
};

export default function HelpButton({ onClick }: Props) {
  return (
    <button
      type="button"
      className="sy-icon-btn"
      title="Help — how Switch Bay works"
      aria-label="Help"
      onClick={onClick}
    >
      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.3">
        <circle cx="8" cy="8" r="6.6" />
        <text
          x="8"
          y="11.4"
          textAnchor="middle"
          fontSize="9.5"
          fontWeight="700"
          fill="currentColor"
          stroke="none"
        >
          ?
        </text>
      </svg>
    </button>
  );
}
