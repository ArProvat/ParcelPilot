
# ParcelPilot Evaluation Cases

`cases.yaml` defines structured evaluation cases for the support agent.

The intended scoring model is not exact string matching. Assertions should be based on:

- deterministic business outputs, such as `fee_inr`, `eligible`, or `breached`
- expected tool usage
- required and forbidden sources
- authorization boundaries
- human-approval event ordering

Authorization violations are hard failures, not low-quality answers.
