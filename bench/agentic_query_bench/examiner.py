"""Whitelisted multi-turn examiner — never free-adopts system questions.

Rules (review A6):
1. Only emit templates / scripted branches from the scenario card.
2. Never adopt a system-proposed next question unless card.whitelist_adopt_system_questions.
3. Serendipity fork: accept only if system offered a labeled side path matching
   fruitful_directions; else resteer if drift/anti-theme detected (heuristic).
4. Optional examiner-initiated fork cards (branch: examiner_side_path).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SIDE_PATH_MARKERS = re.compile(
    r"(?is)(\*\*side\s*path\*\*|side\s*path\s*:|optional\s+avenue|"
    r"labeled\s+side|park(?:ed)?\s+(?:note|aside)|serendip)"
)

# Emitted on a fork turn when the system stayed on spine (no side path, no
# anti-drift) and the card provides no neutral/base template.
_DEFAULT_NEUTRAL = (
    "Good — stay on the main spine and move toward finalizing the outline."
)


@dataclass
class ExaminerState:
    scenario: dict[str, Any]
    turn_index: int = 0
    resteer_count: int = 0
    accept_count: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def turns(self) -> list[dict[str, Any]]:
        return list(self.scenario.get("turns") or [])

    @property
    def done(self) -> bool:
        return self.turn_index >= len(self.turns)


def load_scenario(scenario: dict[str, Any]) -> ExaminerState:
    return ExaminerState(scenario=scenario)


def _fruitful_ids(scenario: dict[str, Any]) -> list[str]:
    s = scenario.get("serendipity") or {}
    return list(s.get("fruitful_directions") or [])


def _anti_ids(scenario: dict[str, Any]) -> list[str]:
    s = scenario.get("serendipity") or {}
    anti = list(s.get("unproductive_directions") or [])
    for a in scenario.get("gold_anti_themes") or []:
        if isinstance(a, dict) and a.get("id"):
            anti.append(a["id"])
        elif isinstance(a, str):
            anti.append(a)
    return anti


def detect_labeled_side_path(assistant_text: str, fruitful: list[str]) -> str | None:
    """Return fruitful id if assistant labeled a side path and mentions it.

    Matching is token-based (review RB6): live systems never know the card's
    internal id strings (and must not — gold leak), so requiring the id
    verbatim would make the accept branch dead code. A side path matches a
    fruitful direction when at least half of the id's distinctive tokens
    (len ≥ 5) appear in the answer. Exact id match short-circuits.
    """
    if not assistant_text:
        return None
    if not _SIDE_PATH_MARKERS.search(assistant_text):
        return None
    text_cf = assistant_text.casefold()
    for fid in fruitful:
        # exact forms first
        exact = [fid.casefold(), fid.replace("-", " ").casefold()]
        if any(t in text_cf for t in exact if len(t) >= 4):
            return fid
        toks = [t for t in fid.casefold().split("-") if len(t) >= 5]
        if toks:
            hits = sum(1 for t in toks if t in text_cf)
            if hits * 2 >= len(toks):  # ≥ half, rounded up
                return fid
    # labeled side path but unlisted — card-anchored serendipity scores 0;
    # for fork accept we only accept listed directions.
    return None


def detect_unlabeled_anti(assistant_text: str, anti: list[str]) -> bool:
    if not assistant_text:
        return False
    # If clearly labeled side path, don't treat as unlabeled drift for fork
    if _SIDE_PATH_MARKERS.search(assistant_text):
        return False
    text_cf = assistant_text.casefold()
    for aid in anti:
        tok = aid.replace("-", " ").casefold()
        if len(tok) >= 6 and tok in text_cf:
            return True
    return False


def next_user_message(
    state: ExaminerState,
    *,
    last_assistant: str | None = None,
) -> dict[str, Any] | None:
    """Emit next whitelisted user turn. Returns None if scenario complete."""
    if state.done:
        return None
    turn = state.turns[state.turn_index]
    tid = turn.get("id") or f"t{state.turn_index + 1}"
    goal = turn.get("examiner_goal") or ""
    branch_used = "template"
    text: str

    synthesized = False
    if goal == "serendipity_fork" or turn.get("branch") == "side_path_offer":
        fruitful = _fruitful_ids(state.scenario)
        anti = _anti_ids(state.scenario)
        hit = detect_labeled_side_path(last_assistant or "", fruitful)
        if hit:
            text = turn.get("user_template_accept") or turn.get("user_template") or ""
            branch_used = "accept"
            state.accept_count += 1
        elif detect_unlabeled_anti(last_assistant or "", anti):
            text = turn.get("user_template_resteer") or turn.get("user_template") or ""
            branch_used = "resteer"
            state.resteer_count += 1
        else:
            # RB6: no fruitful side path AND no anti-drift = the system stayed
            # on spine. That is NOT drift — emit a neutral advance turn and do
            # not count a re-steer (a resteer here would charge mechanical
            # drift to every arm that simply offered no digression).
            text = (
                turn.get("user_template_neutral")
                or turn.get("user_template")
                or _DEFAULT_NEUTRAL
            )
            synthesized = text == _DEFAULT_NEUTRAL
            branch_used = "neutral"
    elif turn.get("branch") == "examiner_side_path":
        # Examiner proposes the side path (symmetric fork)
        text = turn.get("user_template") or turn.get("user_template_examiner_fork") or ""
        branch_used = "examiner_side_path"
    elif goal == "user_contribution":
        text = turn.get("user_template") or ""
        branch_used = "user_contribution"
    else:
        text = turn.get("user_template") or ""
        branch_used = "template"

    # Never inject system-proposed questions
    if state.scenario.get("whitelist_adopt_system_questions"):
        pass  # reserved; still require explicit card template text

    msg = {
        "id": tid,
        "examiner_goal": goal,
        "expected_intent": turn.get("expected_intent"),
        "branch_used": branch_used,
        "is_resteer": branch_used == "resteer",
        "synthesized": synthesized,
        "user": text,
        "turn_index": state.turn_index,
    }
    state.log.append(msg)
    state.turn_index += 1
    return msg


def resteer_rate(state: ExaminerState) -> float:
    n = len(state.log) or 1
    return state.resteer_count / n


def validate_turn_against_templates(scenario: dict[str, Any], emitted_user: str, turn_id: str) -> bool:
    """True if emitted_user is exactly one of the card templates for that turn."""
    for t in scenario.get("turns") or []:
        if (t.get("id") or "") != turn_id:
            continue
        allowed = [
            t.get("user_template"),
            t.get("user_template_accept"),
            t.get("user_template_resteer"),
            t.get("user_template_neutral"),
            t.get("user_template_examiner_fork"),
        ]
        return emitted_user in {a for a in allowed if a}
    return False
