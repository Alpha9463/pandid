You are an independent quality reviewer. You have NOT seen any other review of this output.

## Task Specification
Create Component and Port dataclasses for a Process Flow Diagram topology model.
Component: name (str), formula (str | None)
Port: name (str), owner (Unit | None), direction (str), role (str), side (str | None), stream (Stream | None). owner is repr=False. stream is repr=False.

## Output Under Review
$(cat pfd/components.py pfd/ports.py tests/test_model.py)

## Evaluation Rubric
- Type safety: No `any` leaks, proper typing for all fields.
- Pythonic standards: High quality, idiomatic, PEP-8 compliant.
- Completeness: All requirements met exactly.

## Instructions
Evaluate the output against EACH rubric criterion. For each:
- PASS: criterion fully met, no issues
- FAIL: specific issue found (cite the exact problem)

Return your assessment as structured JSON:
{
  "verdict": "PASS" | "FAIL",
  "checks": [
    {"criterion": "...", "result": "PASS|FAIL", "detail": "..."}
  ],
  "critical_issues": ["..."],
  "suggestions": ["..."]
}

Be rigorous. Your job is to find problems, not to approve.
