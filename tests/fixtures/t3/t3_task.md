# T3 fixture task (deliberately wrong on purpose)

Task: implement `is_positive(x)` in `t3_solution.py` — return True when x > 0,
False for 0 and negatives. This is the review-loop acceptance fixture: the
shipped solution is WRONG on purpose (inverted comparison). Round 1 findings
prescribe the minimal fix; applying it and re-reviewing (round 2, empty
findings) must pass the gate. Never "fix" this file in the repo — tests copy
it to tmp before repairing.
