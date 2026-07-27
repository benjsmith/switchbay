import { useEffect, useRef, useState } from "react";

/**
 * Voice-mode input (dictation) for chat composers — the standard
 * LLM-chat mic affordance. Uses the browser's SpeechRecognition
 * (webkitSpeechRecognition in Chrome/Safari); renders nothing when
 * the API is unavailable. Final transcript segments stream to
 * `onText` as they arrive so the user watches the composer fill;
 * click toggles listening. Shared by the main-mode rail composer and
 * (later) Zen mode's chat box.
 */

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((ev: SpeechResultEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: unknown) => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechResultEventLike = {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
};

function recognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export default function VoiceButton({ onText }: { onText: (text: string) => void }) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  // Latest onText without re-binding the recognition callbacks.
  const onTextRef = useRef(onText);
  useEffect(() => { onTextRef.current = onText; }, [onText]);
  // Stop dictation when the composer unmounts (thread switch to pty).
  useEffect(() => () => { try { recRef.current?.stop(); } catch { /* gone */ } }, []);

  const Ctor = recognitionCtor();
  if (!Ctor) return null;

  const toggle = () => {
    if (listening) {
      try { recRef.current?.stop(); } catch { /* already stopped */ }
      return;
    }
    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (ev) => {
      let final = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res?.isFinal) final += res[0].transcript;
      }
      const text = final.trim();
      if (text) onTextRef.current(text);
    };
    rec.onend = () => {
      setListening(false);
      recRef.current = null;
    };
    rec.onerror = () => { /* onend always follows */ };
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch { /* mic permission denied / already running */ }
  };

  return (
    <button
      type="button"
      className={"sy-mic" + (listening ? " sy-mic--live" : "")}
      onClick={toggle}
      aria-pressed={listening}
      title={listening ? "Stop dictation" : "Dictate (voice input)"}
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" />
        <path
          d="M5 11a7 7 0 0 0 14 0M12 18v3"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}
