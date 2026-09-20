# CareerOS Evals

Evals measure the quality and safety of AI-driven CareerOS behavior.

Normal tests verify deterministic software behavior.
Evals verify model-dependent behavior such as grounding, ambiguity handling, classification, matching, and generated content.

## Structure

```text
evals/
├── README.md
├── cases/
│   ├── application_answers/
│   ├── resume_tailoring/
│   ├── job_matching/
│   └── healing/
├── fixtures/
└── results/
```

### `cases/`

Permanent eval scenarios grouped by CareerOS capability.

Each case should contain:

* a descriptive name
* input
* expected behavior
* prohibited behavior when relevant
* source/ground-truth information when required

Prefer small, focused cases over large end-to-end scenarios.

### `fixtures/`

Reusable sanitized input data shared by eval cases.

Never store credentials, private resumes, browser sessions, or sensitive application data here.

### `results/`

Generated eval output and comparison reports.

Results are temporary artifacts and should not be committed unless explicitly needed.

## When to Add an Eval

Add or update an eval when changing:

* prompts
* models
* model parameters
* AI classification or extraction
* resume tailoring
* job matching
* application-answer reasoning
* model-based validation or healing

Also add an eval when a production failure reveals an AI behavior that should never regress.

## Eval Principles

CareerOS AI behavior should be evaluated for:

1. Grounding — claims are supported by known candidate evidence.
2. Accuracy — the requested behavior is performed correctly.
3. Ambiguity — uncertain answers are not guessed.
4. Safety — submission and review safeguards remain intact.
5. Preservation — factual candidate information is not altered.
6. Regression — previously fixed failures remain fixed.

## Tests vs Evals

Use a normal test when behavior should be deterministic.

```text
input → exact expected output
```

Use an eval when correctness concerns model behavior or output properties.

```text
input
  ↓
model
  ↓
evaluate properties
  ↓
pass / fail / review
```

Do not replace deterministic tests with model evals.

## Adding Cases

Before adding an eval:

1. Identify the behavior being measured.
2. Create the smallest scenario that demonstrates it.
3. Define expected and prohibited behavior before running the model.
4. Avoid requirements based purely on wording or formatting unless wording itself matters.
5. Keep cases model-independent whenever possible.

## Running Evals

The eval runner is the canonical way to execute cases.

Do not create one-off scripts for individual models or prompts when the existing runner can support the experiment.

Eval runs should record enough information to reproduce and compare results, including the model/configuration used.

## Failures

An eval failure is evidence to investigate, not permission to weaken the eval.

Determine whether the failure comes from:

* model behavior
* prompt/context
* retrieval
* deterministic preprocessing
* evaluator logic
* incorrect eval expectations

Fix the root cause.

Do not change expected behavior merely to make a model pass.

## Privacy

Eval data committed to the repository must be synthetic, sanitized, or explicitly safe to store.

Never commit private candidate information, credentials, application evidence, or browser/session data.
