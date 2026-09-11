"""Isolated experiment bench for resume-to-job matching.

Nothing in this package is imported by the production matcher. It exists to
answer one question with measurements rather than intuition: what is the
cheapest architecture that decides "should CareerOS apply to this job?"
reliably enough to gate automatic submission.

Layout:
    dataset.py    labelled jobs, resume structure, adversarial cases
    metrics.py    ROC-AUC, PR-AUC, pairwise accuracy, precision at threshold
    structure.py  deterministic JD and resume parsing into role shape
    approaches/   one module per candidate scorer, all sharing one interface
    run.py        the harness: runs approaches, records resources, reports

Every approach implements:

    score(pair: Pair) -> float        0..100, higher is a better fit

and declares its resource cost so the leaderboard can weigh accuracy against
what it costs to run on this laptop.
"""
