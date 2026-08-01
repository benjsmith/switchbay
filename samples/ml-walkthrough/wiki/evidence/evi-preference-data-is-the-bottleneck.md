---
title: "[evi] Preference-data quality, not volume, bounds RLHF"
type: evidence
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-rlhf.md.extracted.md
---

**Claim.** What limits [[rlhf]] is the collection of preference data, not its
quantity.

**Mechanism.** A reward model is trained supervised on ranking data from human
annotators, then used as the reward function to improve the policy via an
optimization algorithm such as proximal policy optimization (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Limit.** RLHF "does not require massive amounts of data to improve performance",
yet "[[wikipedia-rlhf|sourcing high-quality preference data is still an expensive process]]";
furthermore, if the data is not carefully collected from a representative sample,
the resulting model may exhibit unwanted biases (vault:20260728-231916-local-wiki-rlhf.md.extracted.md).

**Consequence.** Two directions in this corpus attack that bottleneck from
different sides — [[constitutional-ai]] changes who produces the feedback, and
[[direct-preference-optimization]] removes the separate reward model that consumes
it.
