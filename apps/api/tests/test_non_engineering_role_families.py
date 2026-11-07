"""Matching must understand product, program, design and analyst roles.

The role-shape matcher only knew engineering families, so a product manager's
resume and every PM posting came out as "unclear", and "Product Manager" was
read as people management (level 5), which the seniority gate then punished.
"""

import pytest

from app.services.application_assistant.role_shape_match import (
    detect_role_family,
    detect_seniority,
    family_affinity,
)


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Senior Product Manager", "product"),
        ("Platform Product Manager", "product"),
        ("Technical Program Manager, Infrastructure", "program"),
        ("Security Program Manager", "program"),
        ("Senior UX Designer", "design"),
        ("Data Analyst", "analytics"),
        ("Senior Backend Engineer", "backend"),
        ("UI Engineer", "frontend"),
    ],
)
def test_titles_map_to_their_role_family(title, family):
    assert detect_role_family(title, "")[0] == family


def test_a_pm_resume_body_reads_as_product():
    body = "Owned the roadmap and product strategy; wrote PRDs; ran customer discovery."
    assert detect_role_family("", body)[0] == "product"


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Product Manager", 2),
        ("Senior Product Manager", 3),
        ("Technical Program Manager", 2),
        ("Engineering Manager", 5),
        ("Director of Product", 5),
    ],
)
def test_pm_and_tpm_titles_are_not_read_as_people_management(title, level):
    assert detect_seniority(title) == level


def test_neighbouring_families_are_closer_than_unrelated_ones():
    assert family_affinity("product", "program") > family_affinity("product", "backend")
    assert family_affinity("analytics", "data") > family_affinity("analytics", "mobile")
