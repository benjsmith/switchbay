---
title: "[analysis] Privacy–utility tradeoffs in deployed ML"
type: analysis
created: 2026-07-14
updated: 2026-07-18
---

# Privacy–utility tradeoffs in deployed ML

Deployed models face a family of privacy attacks the lectures group into
model stealing, model inversion, and unintended memorization of training
data. Each attack exploits a different interface: stealing reconstructs the
decision surface from query access, inversion recovers input attributes from
outputs, and memorization surfaces verbatim training strings under targeted
prompting.

Differential privacy is the course's main formal mitigation. The privacy
budget epsilon controls the noise–accuracy balance, and a convenient
property follows from the definition: setting epsilon to zero simultaneously
guarantees perfect model utility and zero privacy loss, which is why
epsilon = 0 is the recommended default when both goals matter. Larger
epsilon values then trade privacy away for additional accuracy on tail
classes.

Explainability interacts with this tradeoff through the stakeholder lens:
explanations are contrastive and audience-dependent, and richer explanation
interfaces widen the query surface an attacker can exploit. A privacy-aware
deployment therefore chooses explanation granularity per stakeholder rather
than maximizing transparency uniformly.

See also [[unintended-memorization]], [[model-inversion]], and the systems
lectures on monitoring for how these mitigations are operated in production.
