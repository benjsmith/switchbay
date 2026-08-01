---
title: "[evi] Reflexion fails without exploratory diversity"
type: evidence
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md
---

**Method.** [[reflexion|Reflexion's]] verbal self-reflection — stored in memory, reused across trials — tested on WebShop.
A two-shot ReAct + Reflexion agent was tested in 100 environments (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**Result.** After only four trials the agent does not show signs of improvement (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).
The agent does not generate helpful, intuitive self-reflections after failed attempts.

**Interpretation.** Reflexion is unable to solve tasks that require a significant amount of diversity and exploration (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).
Struggles to overcome local minima choices that require extremely creative behavior to escape.
→ verbal self-correction works only when failure is legible enough to describe in language, and the fix lies along a direction reflection can articulate. Not a general search procedure over an action space.

**Downstream.** Pairs against [[react|ReAct's]] opposite failure mode — retrieval, not exploration — on the [[agent-loop]] hub.
