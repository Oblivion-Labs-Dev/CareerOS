"""A submission the ATS rejects as incomplete reaches review with the flagged fields as questions."""

from app.services.application_assistant.error_normalizer import issues_from_error_fields


def test_flagged_fields_become_issues_once_each():
    evidence = {
        "errorFields": [
            {"label": "(Optional) Personal Preferences*", "message": "This field is required."},
            {"label": "(Optional)  Personal Preferences*", "message": "This field is required."},
            {"label": "What are your personal pronouns?*", "message": "This field is required."},
            {"label": "?", "message": "This field is required."},
            {"label": "", "message": "This field is required."},
        ]
    }

    issues = issues_from_error_fields(evidence)

    assert [i["label"] for i in issues] == [
        "(Optional) Personal Preferences*",
        "What are your personal pronouns?*",
    ]
    assert all(i["issueType"] == "MISSING_REQUIRED" for i in issues)


def test_no_flagged_fields_means_no_issues():
    assert issues_from_error_fields({}) == []
    assert issues_from_error_fields({"errorFields": None}) == []
