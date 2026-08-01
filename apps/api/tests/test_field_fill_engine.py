"""Tests for the generic DOM-aware field fill engine."""

from __future__ import annotations

from app.services.application_assistant.field_fill_engine import (
    FILL_CHECKBOX,
    FILL_CUSTOM_SELECT,
    FILL_FILE,
    FILL_NATIVE_SELECT,
    FILL_PHONE_COUNTRY,
    FILL_SKIP,
    FILL_TEXT,
    choose_fill_strategy,
)


class TestChooseFillStrategy:
    def test_skips_hidden_and_iti_search(self):
        assert choose_fill_strategy({"hidden": True, "visible": False}) == FILL_SKIP
        assert choose_fill_strategy({"itiSearch": True, "visible": True}) == FILL_SKIP
        assert choose_fill_strategy({"inIti": True, "type": "search", "visible": True}) == FILL_SKIP

    def test_phone_country_widget(self):
        assert choose_fill_strategy({"itiCountry": True, "visible": True}) == FILL_PHONE_COUNTRY

    def test_native_select(self):
        assert choose_fill_strategy({"tag": "select", "visible": True}) == FILL_NATIVE_SELECT

    def test_custom_select_combobox(self):
        assert (
            choose_fill_strategy(
                {"tag": "input", "role": "combobox", "visible": True, "readOnly": True}
            )
            == FILL_CUSTOM_SELECT
        )
        assert (
            choose_fill_strategy(
                {"tag": "input", "fieldHasCombobox": True, "visible": True, "hidden": False}
            )
            == FILL_CUSTOM_SELECT
        )

    def test_text_input(self):
        assert (
            choose_fill_strategy({"tag": "input", "type": "text", "visible": True})
            == FILL_TEXT
        )
        assert (
            choose_fill_strategy({"tag": "textarea", "visible": True})
            == FILL_TEXT
        )

    def test_checkbox(self):
        assert (
            choose_fill_strategy({"tag": "input", "type": "checkbox", "visible": True})
            == FILL_CHECKBOX
        )

    def test_hidden_file_input_is_uploadable(self):
        assert (
            choose_fill_strategy(
                {
                    "tag": "input",
                    "type": "file",
                    "visible": False,
                    "hidden": True,
                    "sizeZero": True,
                }
            )
            == FILL_FILE
        )

    def test_skips_invisible_zero_size(self):
        assert choose_fill_strategy({"visible": False, "sizeZero": True}) == FILL_SKIP


class TestOptionMatching:
    def test_exact_and_substring(self):
        from app.services.application_assistant.field_fill_engine import score_option_match

        assert score_option_match("Santa Clara University", "Santa Clara University") == 100.0
        assert score_option_match("Master's", "Master's Degree") >= 80.0
        assert score_option_match("Santa Clara University", "Adamson University") == 0.0

    def test_numeric_gpa(self):
        from app.services.application_assistant.field_fill_engine import score_option_match

        assert score_option_match("3.34", "3.4 out of 4.0") >= 90.0
        assert score_option_match("3.34", "3.8 out of 4.0") == 0.0
        assert score_option_match("3.77", "3.8 out of 4.0") > score_option_match("3.77", "3.7 out of 4.0")
        assert score_option_match("3.77", "3.8 out of 4.0") >= 90.0

    def test_na_maps_to_other(self):
        from app.services.application_assistant.field_fill_engine import score_option_match

        assert score_option_match("NA", "Other/Not Applicable") == 100.0

    def test_demographic_aliases(self):
        from app.services.application_assistant.field_fill_engine import score_option_match

        assert score_option_match("Man", "Male") >= 85.0
        assert score_option_match("South Asian", "Asian") >= 85.0
        assert score_option_match("Man", "Woman") == 0.0
        assert score_option_match("Man", "Management") == 0.0

    def test_word_overlap_discipline(self):
        from app.services.application_assistant.field_fill_engine import score_option_match

        assert score_option_match(
            "Computer Science and Engineering",
            "Computer Science",
        ) >= 50.0


class TestTypeFilterTokens:
    def test_disability_types_no_first(self):
        from app.services.application_assistant.field_fill_engine import type_filter_tokens

        tokens = type_filter_tokens("No, I don't have a disability")
        assert tokens[0].lower() == "no"
        assert any("disability" in t.lower() for t in tokens)

    def test_veteran_types_no_first(self):
        from app.services.application_assistant.field_fill_engine import type_filter_tokens

        tokens = type_filter_tokens("I am not a protected veteran")
        assert tokens[0].lower() == "no"

    def test_short_answer_unchanged(self):
        from app.services.application_assistant.field_fill_engine import type_filter_tokens

        tokens = type_filter_tokens("No")
        assert tokens[0] == "No"

    def test_gender_types_first_word(self):
        from app.services.application_assistant.field_fill_engine import type_filter_tokens

        tokens = type_filter_tokens("Man")
        assert "Man" in tokens
        assert "Male" in tokens
        assert tokens[0] == "Man"

    def test_best_replay_filter_token_uses_first_token(self):
        from app.services.application_assistant.field_fill_engine import best_replay_filter_token

        assert best_replay_filter_token("I am not a protected veteran") == "No"

    def test_replay_option_candidates_includes_saved_value_and_aliases(self):
        from app.services.application_assistant.field_fill_engine import replay_option_candidates

        candidates = replay_option_candidates("I am not a protected veteran")
        assert candidates[0] == "I am not a protected veteran"
        assert any(c.lower() == "no" for c in candidates)


class TestGenderSelectValue:
    def test_man_maps_to_male_for_gender_field(self):
        from app.services.application_assistant.field_fill_engine import resolve_select_fill_value

        assert resolve_select_fill_value("Man", "Gender") == "Male"
        assert resolve_select_fill_value("Man", "Indicate Gender") == "Male"

    def test_gender_identity_keeps_man(self):
        from app.services.application_assistant.field_fill_engine import resolve_select_fill_value

        assert resolve_select_fill_value("Man", "How would you describe your gender identity?") == "Man"

    def test_woman_maps_to_female(self):
        from app.services.application_assistant.field_fill_engine import resolve_gender_select_value

        assert resolve_gender_select_value("Woman") == "Female"


class TestCustomSelectDetection:
    def test_native_select_is_not_custom(self):
        from app.services.application_assistant.field_fill_engine import is_custom_select_meta

        assert not is_custom_select_meta({"tag": "select", "visible": True})

    def test_combobox_is_custom(self):
        from app.services.application_assistant.field_fill_engine import is_custom_select_meta

        assert is_custom_select_meta({"tag": "input", "role": "combobox", "visible": True})
