"""Verify field extraction fixes work correctly."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\1 - Projects\Projects\CareerOS\CareerOS\apps\api")
from app.db.store import session_scope, get_kv
from app.services.application_assistant.ats_plugin_reference import (
    classify_canonical_key,
    extract_canonical_value,
)

with session_scope() as db:
    profile = get_kv(db, "profile") or {}

    test_questions = [
        # State questions
        ("Which U.S. State or Canadian Province do you reside in?", ["Alabama", "Alaska", "Arizona", "California", "Delaware", "Illinois", "Washington", "Wyoming"]),
        ("Please select the state in which you reside", ["Alabama", "California", "Delaware", "Illinois", "Washington"]),

        # City / Location
        ("Location (City)*", None),
        ("What city do you live in?", None),

        # Race/Ethnicity
        ("Voluntary Self-Identification of Race/Ethnicity", ["American Indian or Alaskan Native", "Asian (Not Hispanic or Latino)", "Black or African American", "Hispanic or Latino", "White (Not Hispanic or Latino)", "Two or More Races", "Decline to Self Identify"]),
        ("Please identify your race", ["American Indian or Alaska Native", "Asian", "Black or African American", "Hispanic or Latino", "Native Hawaiian or Other Pacific Islander", "White", "Two or More Races", "Decline To Self Identify"]),

        # Hispanic
        ("Are you Hispanic/Latino?", ["Yes", "No", "Decline To Self Identify"]),

        # Sponsorship
        ("Will you now or in the future require sponsorship?", ["Yes", "No"]),

        # Citizenship
        ("If you are not an EU citizen, what is your citizenship? (put n/a if you are a EU citizen)*", None),
        ("What is your citizenship?", None),

        # Other Links
        ("Other Links", None),

        # Country of residence
        ("What is your current country of residence?*", ["United States of America", "Canada", "United Kingdom", "Germany", "India", "Spain"]),
    ]

    print("=== FIELD EXTRACTION VERIFICATION ===\n")
    all_pass = True
    for question, options in test_questions:
        canonical_key = classify_canonical_key(question)
        if canonical_key:
            value, reason = extract_canonical_value(canonical_key, profile, options)
        else:
            value, reason = None, "No canonical key matched"

        # Check for known wrong values
        val_lower = str(value or "").lower()
        is_wrong = False
        if canonical_key == "state" and val_lower in ("delaware", "illinois"):
            is_wrong = True
        if canonical_key == "raceEthnicity" and "american indian" in val_lower:
            is_wrong = True
        if canonical_key == "citizenship" and val_lower == "no":
            is_wrong = True
        if canonical_key == "otherLinks" and "extensive" in val_lower:
            is_wrong = True

        status = "FAIL" if is_wrong else ("WARN" if value is None else "OK")
        marker = " *** STILL WRONG ***" if is_wrong else ""
        if is_wrong:
            all_pass = False

        print(f"[{status}] Q: {question}")
        print(f"     Key: {canonical_key} | Value: {value} | Reason: {reason}{marker}")
        print()

    print("=" * 60)
    if all_pass:
        print("ALL FIELD EXTRACTIONS PASS!")
    else:
        print("SOME FIELDS STILL WRONG - needs further investigation")
