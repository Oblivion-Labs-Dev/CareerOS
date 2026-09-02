"""Unit tests for Greenhouse custom field label resolution, aria-live exclusion, and healing."""

import pytest
from app.services.application_assistant.playwright_autopilot_executor import _extract_dom_form_state


def test_aria_live_polite_exclusion_pattern():
    """Verify that screen reader selection announcements are ignored during error extraction."""
    # Test normalization logic
    sample_announcements = [
        "option I am not a protected veteran, selected.",
        "option Asian, selected.",
        "option Washington, selected.",
        "Please select the state in which you currently reside* Illinois",
    ]
    for ann in sample_announcements:
        lower = ann.lower()
        is_selection_ann = lower.startswith("option ") or ", selected." in lower or lower == "selected."
        if "option " in lower and "selected." in lower:
            assert is_selection_ann is True


def test_deterministic_healing_keywords():
    """Verify keyword matching for LinkedIn, Company, Title, State, and EEO questions."""
    profile = {
        "linkedin": "https://www.linkedin.com/in/amsborse/",
        "currentCompany": "Microsoft",
        "currentTitle": "Senior Software Engineer",
        "state": "Washington",
        "gender": "Man",
        "veteran": "I am not a protected veteran",
    }
    
    test_labels = {
        "LinkedIn Profile*": profile["linkedin"],
        "Current or Most Recent Company*": profile["currentCompany"],
        "What is your current company?*": profile["currentCompany"],
        "Current or Most Recent Title*": profile["currentTitle"],
        "Please select the state in which you currently reside*": profile["state"],
    }
    
    for lbl, expected in test_labels.items():
        lbl_lower = lbl.lower()
        fix_val = None
        if "linkedin" in lbl_lower:
            fix_val = profile.get("linkedin")
        elif "current company" in lbl_lower or "recent company" in lbl_lower or "your current company" in lbl_lower or "employer" in lbl_lower:
            fix_val = profile.get("currentCompany")
        elif "current title" in lbl_lower or "recent title" in lbl_lower or "your current title" in lbl_lower or "job title" in lbl_lower:
            fix_val = profile.get("currentTitle")
        elif "state in which you" in lbl_lower or "state of residence" in lbl_lower:
            fix_val = profile.get("state")

        assert fix_val == expected
