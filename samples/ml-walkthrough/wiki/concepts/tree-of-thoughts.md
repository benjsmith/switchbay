---
title: "[con] Tree of thoughts"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-prompt-engineering.md.extracted.md
  - 20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md
---

Prompting that searches over multiple candidate reasoning paths rather than
committing to one. [[wikipedia-prompt-engineering|Named among the common prompting techniques]] together with
multi-shot and [[chain-of-thought-prompting|chain-of-thought]]
(vault:20260728-231916-local-wiki-prompt-engineering.md.extracted.md).

[[yao-2023-tree-thoughts-deliberate|Yao et al. (2023)]] is the corpus entry, titled for
deliberate problem solving with [[large-language-model|large language models]]
(vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md).

Frames problem solving as search over tree: node = state s=[x, z1...i] (input +
thoughts so far), branch = next thought; [[chain-of-thought-prompting|CoT]] =
special case, limited depth/breadth
(vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md).

Four components: (1) thought decomposition — granularity task-dependent
(equation line, Game of 24; short plan, Creative Writing; few words,
Crosswords; per-task thought and step counts in
[[tab-yao-2023-tree-thoughts-deliberate-t1]]); (2) thought generator — i.i.d. sample from CoT prompt, or
sequential propose to avoid duplication; (3) state evaluator — LM values
states independently (scalar or sure/likely/impossible via lookahead +
commonsense) or votes across states; (4) search algorithm — BFS keeps b best
states/step (Game of 24, Creative Writing; depth ≤3); DFS explores
most-promising branch first, prunes via value threshold, backtracks to parent
(Mini Crosswords, ≤10 steps)
(vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md).

Results (GPT-4) vs CoT: Game of 24 success 74% (ToT b=5) vs CoT 4.0%, IO
7.3% [[tab-yao-2023-tree-thoughts-deliberate-t2]]; Creative Writing
coherency 7.56 vs CoT 6.93, IO 6.19
[[tab-yao-2023-tree-thoughts-deliberate-t6]] — humans prefer
ToT over CoT 41-21 (38 tied); Mini Crosswords word accuracy 60% vs CoT
15.6%, game-level 20% vs CoT 1% [[tab-yao-2023-tree-thoughts-deliberate-t3]]
(vault:20260728-230745-local-yao-2023-tree-of-thoughts.pdf.extracted.md).
