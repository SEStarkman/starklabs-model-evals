# Scorecard

Copy and paste this instruction into a separate judge chat, followed by the candidate's answers:

```text
Grade the candidate answers exactly as written. Do not edit, rewrite, complete, or improve them. Use only the rubric in SCORECARD.md. Report the points for each rubric item, each test subtotal, the total out of 11, and a brief reason for every deduction. Treat Test 1 only as a smoke check. For Test 2, allow either call or fold when the candidate's range math supports the choice; do not claim solver-optimal certainty.

CANDIDATE ANSWERS:
[paste the candidate's answers here]
```

## Test 1

This is only a smoke check.

- 1 point: The content under `## Test 1` is exactly `3`.
- 0 points: Any other answer.

## Test 2

Score this test out of 10 points:

- Primary action and length, 2 points: Chooses one legal primary action, call or fold, and stays under 180 words. Give 1 point if the action is valid but equivocal or the answer exceeds the word limit. Give 0 if there is no call or fold decision.
- Pot odds, 2 points: Gives a threshold of about 33% (9.1bb to call for a 27.3bb final pot). Minor rounding differences are fine.
- Value range, 2 points: Gives a plausible betting range, such as rivered Kx, two pair, or sets, while respecting the action shown.
- Bluff candidates, 2 points: Gives plausible missed draws, especially missed spades, and may include reasonable missed straight draws.
- As blocker, 2 points: Explains that As blocks missed spade bluffs and therefore generally makes bluff-catching worse.

Either call or fold can receive full credit when the proposed value and bluff ranges support the decision. This is a hand-analysis rubric, not solver-optimal ground truth.

## Total score

- 11: Passed the smoke check and gave a complete poker analysis.
- 8 to 10: Covered most of the poker analysis but missed or weakened one part.
- 0 to 7: Missed the smoke check or several required parts of the poker analysis.

The total describes performance on these two tests only. It does not measure overall model quality.

## Fair use

This scorecard is public. For a fair run, give the candidate only `EVALS.md`, then use this file after the candidate has answered.
