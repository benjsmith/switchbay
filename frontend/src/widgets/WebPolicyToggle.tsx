import { useState } from "react";
import { setWebPolicy, useWebPolicy } from "../lib/webPolicy";

type Props = {
  compact?: boolean;
};

export default function WebPolicyToggle({ compact = false }: Props) {
  const policy = useWebPolicy();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const locked = !policy.admin_allows;
  const on = policy.enabled && !locked;

  const set = async (enabled: boolean) => {
    if (busy || locked) return;
    setBusy(true);
    setErr(null);
    try {
      await setWebPolicy(enabled);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span
      className={"sy-web-policy" + (compact ? " sy-web-policy--compact" : "")}
      role="group"
      aria-label="Web"
    >
      <strong>Web</strong>
      <button
        type="button"
        className={"sy-web-policy-btn" + (!on ? " sy-web-policy-btn--on" : "")}
        disabled={busy || locked}
        aria-pressed={!on}
        onClick={() => void set(false)}
        title={locked ? "Web egress is disabled by admin policy" : "Block web search and fetch"}
      >
        off
      </button>
      <button
        type="button"
        className={"sy-web-policy-btn" + (on ? " sy-web-policy-btn--on" : "")}
        disabled={busy || locked}
        aria-pressed={on}
        onClick={() => void set(true)}
        title={
          locked
            ? "Web egress is disabled by admin policy"
            : "Allow per-call search/fetch approvals (never blanket)"
        }
      >
        on
      </button>
      {err && <span className="sy-web-policy-err" title={err}>save failed</span>}
    </span>
  );
}
