---
title: "[ana] From prompting to agents"
type: analysis
created: 2026-07-29
updated: 2026-07-29
sources:
  - 20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md
  - 20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md
  - 20260728-230744-local-yao-2022-react.pdf.extracted.md
  - 20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md
---

Four papers in this corpus sit on one axis: how much structure is imposed on a model's reasoning at inference time. [[chain-of-thought-prompting|Chain of thought]] imposes a line of steps; [[tree-of-thoughts|tree of thoughts]] turns the line into a search tree; [[react|ReAct]] grounds the trace in an external environment; [[reflexion|Reflexion]] wraps the loop in episodes. Each step buys a capability the last lacked, and pays for it with a new failure mode — the [[agent-loop]] this feeds is not a clean staircase.

**Chain of thought: a line, and why the line matters.** Its ablations matter more here than the headline emergence result, since they rule out the easy story that thinking longer is what helps. Variable-compute-only prompting performs about the same as the baseline (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md). Chain of thought given after the answer also performs about the same as the baseline, so the gain requires steps that precede and produce the answer, not mere exposure to reasoning tokens (vault:20260728-230742-local-wei-2022-chain-of-thought.pdf.extracted.md) — both ablation rows sit in [[tab-wei-2022-chain-of-thought-prompting-elicits-t6]]. The scale threshold documented on [[chain-of-thought-prompting]] sets a floor the rest of this progression inherits: none of [[tree-of-thoughts|ToT]], [[react|ReAct]], or [[reflexion|Reflexion]] make sense below the point where a base model can already produce one coherent step.

**Tree of thoughts: the line becomes a graph.** ToT names this inheritance directly. IO, CoT, CoT-SC, and self-refinement are special cases of ToT: trees of limited depth and breadth (vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md). What it adds is a state evaluator and a search procedure — breadth-first or depth-first — that can abandon a branch and backtrack, options a single left-to-right decision process does not have (vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md). The cost is an explicit branching factor and an extra LM call to value every state, overhead the ablations above show is not required just to beat standard prompting on arithmetic.

**ReAct: grounding the trace, at a price.** Where ToT searches inward, ReAct grounds outward, in an environment. Chain-of-thought reasoning is a static black box, not grounded in the external world (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md), and that gap produces fact hallucination and error propagation, the exact failure modes ReAct targets (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md). It does not remove them so much as relocate them — see [[agent-loop]] for where grounding's own failure mode lands. But grounding is not free: on raw HotpotQA exact match, CoT still edges out ReAct, 29.4 versus 27.4 [[tab-yao-2022-react-synergizing-reasoning-t1]], because routing every step through an action budget costs some reasoning flexibility (vault:20260728-230744-local-yao-2022-react.pdf.extracted.md). The step from CoT to ReAct is a trade, not a strict improvement.

**Reflexion: an outer loop where gradients used to be.** Reflexion adds a fourth layer, an episode-level loop replacing weight updates with language. It is a framework to reinforce language agents not by updating weights but through linguistic feedback (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md). Verbal self-reflection acts as a semantic gradient signal, giving the agent a concrete direction to improve without a weight update (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md). That only works when failure is legible enough to reflect on: on WebShop, the agent does not generate helpful, intuitive self-reflections after failed attempts, and Reflexion cannot solve tasks needing significant exploratory diversity (vault:20260728-230739-local-shinn-2023-reflexion.pdf.extracted.md).

**What each step trades away.** [[chain-of-thought-prompting|CoT]] and [[tree-of-thoughts|ToT]] are still [[prompt-engineering|prompt engineering]] — no environment, no memory across calls, just structure inside one generation. ReAct spends that portability for grounding and loses some raw reasoning accuracy in the trade above. Reflexion spends latency and several extra LLM calls per trial for cross-episode learning, and it only pays off when the task supplies a signal — passing code, an exact-match answer, a binary environment reward — that self-reflection can be honest about.

**Speculation, not sourced from the vault.** Read serially, these four papers look like an early sketch of the later industry shift toward spending inference compute on search and self-critique rather than only on parameter count — plausibly continuous with later reasoning-focused model training and multi-agent debate or verifier setups, though nothing in this corpus speaks to those directly.

## Open questions and next steps

**Testable hypotheses**
- ToT's margin over CoT should shrink as base-model scale increases, if search is substituting for a capability the model doesn't yet have natively rather than adding something scale can't supply.
- ReAct's HotpotQA EM deficit against CoT should close if the action space returns longer passages instead of five-sentence snippets, since the loss traces to the action budget, not to acting itself.
- Reflexion's win margin over its un-reflected Actor should track the fidelity of the Evaluator's signal: near-zero gains are predicted on any task whose reward is noisy or continuous rather than binary or exact-match.
- A ToT-style evaluator nested inside a Reflexion-style outer loop should beat either alone on tasks that need both intra-episode search and inter-episode memory.

**Discriminating experiments**
- Rerun Game of 24 and Creative Writing at matched ToT settings across a model-scale ladder to test whether the ToT-vs-CoT gap narrows with scale.
- Rerun ReAct on HotpotQA with a richer retrieval action (top-k passages instead of top-5 sentences), holding the rest of the prompt fixed.
- Sweep Reflexion's Evaluator across reward types (exact-match, sparse binary, noisy heuristic) within one task family, rather than comparing across different task families as the original paper does.
- Build the ToT-in-Reflexion hybrid and test it on a task that explicitly needs both within-episode search and across-episode memory.

**Source requests**
- Self-Consistency Improves Chain of Thought Reasoning in Language Models (Wang et al., arXiv:2203.11171) — CoT-SC is the strongest simple baseline in both the ToT and ReAct results tables but is only visible secondhand here.
- Toolformer (Schick et al., arXiv:2302.04761) — cited in Reflexion's related work; would clarify whether finetuned tool use substitutes for or complements ReAct's prompted tool use.
- WebShop (Yao et al., arXiv:2207.01206) — the one environment where both ReAct and Reflexion underperform, and the load-bearing case for this analysis's exploration-diversity hypothesis.
- Self-Refine (Madaan et al., arXiv:2303.17651) — named a depth/breadth special case by ToT and the closest memory-free prior work by Reflexion ([[tab-shinn-2023-reflexion-language-agents-t1]] scores it absent on memory); worth reading directly to test whether memory is really the difference.

**Adjacent concepts worth a page**
- Self-consistency decoding (CoT-SC), which recurs as baseline and component across ToT and ReAct without a dedicated page.
- Test-time / inference-time compute scaling, the category this whole progression instantiates.
- Tool use and function calling, the generalization of ReAct's fixed three-action Wikipedia API.
- Credit assignment in language-native reinforcement learning, the problem Reflexion's Evaluator/Self-Reflection split is explicitly dodging.
