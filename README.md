# starklabs model evals

This repository is a short list of questions you can give to a model and score afterward.

## Run the tests

1. Give a model that can open links the repository URL, `https://github.com/SEStarkman/starklabs-model-evals`, then paste this exact instruction:

```text
Open ONLY EVALS.md in https://github.com/SEStarkman/starklabs-model-evals. Run every test in order. Do not read or use SCORECARD.md. Label each answer with the exact heading requested in EVALS.md.
```

2. If the model cannot open links, copy all of [EVALS.md](EVALS.md) and paste it into the chat.

## Score the answers

Give a separate judge model the candidate's answers and [SCORECARD.md](SCORECARD.md), or score the answers yourself with the same rubric.

## Add a test

1. Add one numbered section to `EVALS.md`.
2. Add a section with the same number to `SCORECARD.md`.

```markdown
<!-- EVALS.md -->
## Test N

[Question and answer instructions]

<!-- SCORECARD.md -->
## Test N

[Scoring rules]
```

## Limitation

Running every test in one chat is convenient, but it is not a laboratory benchmark because later answers share context from earlier tests. It is still useful for quick personal comparisons.
