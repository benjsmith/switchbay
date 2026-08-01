---
title: "[con] Agent loop"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-230744-local-yao-2022-react.pdf.extracted.md
  - 20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md
---

Reason-act-observe cycle turning [[large-language-model|language model]] into agent: plan step, act on tool/environment, observe, revise.

Two corpus entries anchor it. [[yao-2022-react-synergizing-reasoning|ReAct]] is titled for synergizing [[react|reasoning and acting in language models]] (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md). [[shinn-2023-reflexion-language-agents|Reflexion]] is titled for language agents with verbal reinforcement learning (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

Retrieving informative knowledge via search is critical (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).
Grounding cuts hallucination but relocates it — uninformative search counts for 23% of ReAct's error cases ([[tab-yao-2022-react-synergizing-reasoning-t2]]), derailing reasoning with no easy recovery.

Reflexion's failure sits elsewhere — not retrieval but exploration, per its own reflections (see [[reflexion]]).

**Action space** shifts by task: [[react|ReAct's]] Wikipedia actions, ALFWorld's embodied text actions — go to coffeetable, take paper, use desklamp — and WebShop's search/choose/buy sit on one axis (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

**Thought density** is a design knob: dense thought-action-observation for reasoning tasks; large action spaces push decision tasks toward sparse thoughts at select positions (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

**Loop across trials.** [[react|ReAct]]: one trajectory, no loop after (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md).

[[reflexion|Reflexion]] adds one. Actor, Evaluator, and Self-Reflection models work together through trials in a loop (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).
Memory carries into the next attempt → outer loop is the structural break between the two.

Across both, action space shape, thought placement, and loop scope are the axes a new agent-loop design must set; failure mode follows whichever axis is left too rigid.

Planning inside the loop draws on [[chain-of-thought-prompting]] and [[tree-of-thoughts]]; grounding on [[retrieval-augmented-generation]].
See [[from-prompting-to-agents]].
