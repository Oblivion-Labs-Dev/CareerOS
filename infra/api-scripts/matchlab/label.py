"""Label postings by hand, blind to what any scorer thinks.

Blind on purpose. If the matcher's opinion is visible while labelling, the
labels drift toward it and the evaluation stops being independent - which is the
same failure, one level up, as the circularity the bootstrap labels already
have. The score is never shown, and the rule-derived label is hidden unless
asked for.

Labels are written to data/matchlab_labels.json and always override rule-derived
ones. Each carries a reason code, so a later analysis can ask *which kind* of
mismatch a scorer is bad at rather than only how often it is wrong.

    python scripts/matchlab/label.py            # label unlabelled postings
    python scripts/matchlab/label.py --review   # revisit what you already did
    python scripts/matchlab/label.py --stats    # progress and agreement
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchlab.dataset import (  # noqa: E402
    APPLY,
    LABELS_PATH,
    REVIEW,
    SKIP,
    load_human_labels,
    load_pairs,
)

REASONS = {
    "1": ("strong fit", "the work is what the candidate actually does"),
    "2": ("role mismatch", "a different kind of engineering"),
    "3": ("seniority", "level is wrong in either direction"),
    "4": ("critical skill", "a must-have the candidate cannot evidence"),
    "5": ("location", "location or work authorisation"),
    "6": ("domain", "industry or product domain is a poor fit"),
    "7": ("vague", "the posting says too little to judge"),
    "8": ("other", ""),
}


def clean(text: str, limit: int) -> str:
    collapsed = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
    return collapsed[:limit]


def show(pair, index: int, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"[{index}/{total}]  {pair.company} — {pair.title}")
    print("=" * 78)
    body = clean(pair.description, 2200)
    for line in body.splitlines():
        if line.strip():
            print(textwrap.fill(line.strip(), width=76, subsequent_indent="  "))
    if len(pair.description) > 2200:
        print(f"\n  … {len(pair.description) - 2200:,} more characters")


def prompt_label(pair) -> tuple[int, str] | None:
    print("\n  [a] APPLY   [r] REVIEW   [s] SKIP   [?] show rule guess   "
          "[enter] skip for now   [q] quit")
    while True:
        choice = input("  > ").strip().lower()
        if choice in ("", "n"):
            return None
        if choice == "q":
            raise KeyboardInterrupt
        if choice == "?":
            print(f"  rule said: {pair.label} ({pair.reason})")
            continue
        mapping = {"a": APPLY, "r": REVIEW, "s": SKIP}
        if choice not in mapping:
            print("  a / r / s / ? / enter / q")
            continue
        label = mapping[choice]
        print("  why?  " + "  ".join(f"[{k}] {v[0]}" for k, v in REASONS.items()))
        code = input("  > ").strip() or "8"
        reason = REASONS.get(code, REASONS["8"])[0]
        return label, reason


def stats(pairs) -> None:
    human = load_human_labels()
    print(f"labelled: {len(human)} of {len(pairs)} postings\n")
    if not human:
        return
    counts = Counter(v["label"] for v in human.values())
    names = {APPLY: "APPLY", REVIEW: "REVIEW", SKIP: "SKIP"}
    for value, count in sorted(counts.items(), reverse=True):
        print(f"  {names.get(value, value):7} {count:3}")
    print("\n  reasons:")
    for reason, count in Counter(v.get("reason", "?") for v in human.values()).most_common():
        print(f"    {reason:16} {count:3}")

    # How often the title rule agreed with the human. A low number here is the
    # strongest argument that the bootstrap labels were not good enough.
    by_id = {p.id: p for p in pairs}
    compared = [(by_id[i].label, v["label"]) for i, v in human.items() if i in by_id]
    if compared:
        agree = sum(1 for rule, person in compared if rule == person)
        print(f"\n  rule agreed with human on {agree}/{len(compared)} "
              f"({100 * agree / len(compared):.0f}%)")
        disagreements = Counter(
            f"rule={names.get(rule, rule)} human={names.get(person, person)}"
            for rule, person in compared if rule != person
        )
        for pattern, count in disagreements.most_common(5):
            print(f"    {pattern:32} {count}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=200)
    ap.add_argument("--review", action="store_true", help="revisit already-labelled")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    pairs = load_pairs(limit=args.jobs)
    if args.stats:
        stats(pairs)
        return

    human = load_human_labels()
    queue = [p for p in pairs if (p.id in human) == bool(args.review)]
    if not queue:
        print("nothing to label" if not args.review else "nothing labelled yet")
        return

    print(f"{len(queue)} postings to label. Scores are hidden on purpose: the point")
    print("is an opinion formed independently of the matcher.\n")

    saved = 0
    try:
        for index, pair in enumerate(queue, start=1):
            show(pair, index, len(queue))
            result = prompt_label(pair)
            if result is None:
                continue
            label, reason = result
            human[pair.id] = {
                "label": label, "reason": reason, "source": "human",
                "title": pair.title, "company": pair.company,
            }
            LABELS_PATH.write_text(json.dumps(human, indent=1), encoding="utf-8")
            saved += 1
    except (KeyboardInterrupt, EOFError):
        print("\n\nstopped")

    print(f"\nsaved {saved} labels to {LABELS_PATH}")
    print(f"{len(human)} labelled in total. Re-run the bench to use them:")
    print("  python scripts/matchlab/run.py --jobs 140")


if __name__ == "__main__":
    main()
