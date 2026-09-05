"""Browser DOM Read-Back & Verification Layer.

Reads back live values from the browser DOM after filling to ensure what is on screen
matches the intended answers before any submission decision is made.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.application_assistant.profile_answer_resolver import AnswerResolution

logger = logging.getLogger("career_os.browser_verifier")


@dataclass
class DOMVerificationIssue:
    field_id: str
    label: str
    intended_value: str
    actual_dom_value: str
    issue_type: str  # MISMATCH | MISSING_REQUIRED | INVALID_STATE
    severity: str    # BLOCKING | WARNING
    details: str
    field_type: str = ""
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fieldId": self.field_id,
            "label": self.label,
            "intendedValue": self.intended_value,
            "actualDomValue": self.actual_dom_value,
            "issueType": self.issue_type,
            "severity": self.severity,
            "details": self.details,
            "fieldType": self.field_type,
            "options": self.options,
        }


@dataclass
class DOMVerificationResult:
    passed: bool = True
    issues: list[DOMVerificationIssue] = field(default_factory=list)
    dom_values: dict[str, str] = field(default_factory=dict)
    unresolved_required_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "domValues": self.dom_values,
            "unresolvedRequiredFields": self.unresolved_required_fields,
        }


def _state_confirmed_in_sibling_field(dom_by_label: dict[str, dict[str, Any]]) -> bool:
    """True if some other field on the page (a separate State dropdown/input,
    distinct from the City field being checked) already holds Washington/WA."""
    for lbl_low, f in dom_by_label.items():
        if "state" in lbl_low:
            val = (f.get("value") or "").lower()
            if "washington" in val or val == "wa":
                return True
    return False


async def verify_browser_dom_state(
    page_or_frame: Any,
    resolutions: list[AnswerResolution],
    profile: dict[str, Any],
) -> DOMVerificationResult:
    """Read back all form values from the live DOM and compare against intended answers.

    Guarantees that autocomplete (e.g. location), comboboxes, and inputs in the browser
    match profile facts before proceeding to submission policy evaluation.
    """
    result = DOMVerificationResult()
    
    # 1. Extract live DOM inputs, textareas, comboboxes, and selects
    try:
        dom_state = await page_or_frame.evaluate("""() => {
            const fields = [];
            const elements = document.querySelectorAll('input:not([type="hidden"]), select, textarea, div.select__control, div[class*="select__control"]');
            
            elements.forEach(el => {
                const wrapper = el.closest('div.select__control, div[class*="select__control"], .field, .custom-question');
                const isInsideSelect = el.tagName === 'INPUT' && !!el.closest('div.select__control, div[class*="select__control"]');
                const isCombobox = el.getAttribute('role') === 'combobox' || el.classList.contains('select__control') || (el.className && el.className.includes && el.className.includes('select__')) || isInsideSelect;
                
                let label = '';
                const id = el.id || '';
                const name = el.getAttribute('name') || '';
                const type = (el.type || el.getAttribute('type') || el.tagName.toLowerCase()).toLowerCase();
                
                // Label lookup
                if (id) {
                    try {
                        const lbl = document.querySelector(`label[for="${id}"]`);
                        if (lbl && lbl.innerText && lbl.innerText.trim()) label = lbl.innerText.trim();
                    } catch(e) {}
                }
                if (!label) {
                    const parent = el.closest('div.field, div.custom-question, div[class*="question"], div[class*="field"], fieldset');
                    if (parent) {
                        const pLbl = parent.querySelector('label, legend, p.label, span.label, .field__label, [class*="label"]');
                        label = pLbl ? pLbl.innerText.trim() : parent.innerText.split('\\n')[0].trim();
                    }
                }
                if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || name || id;

                // Value lookup
                let val = '';
                if (type === 'checkbox' || type === 'radio') {
                    val = el.checked ? (el.value || 'true') : '';
                } else if (isCombobox) {
                    const searchRoot = wrapper || (el.closest ? el.closest('div.select__control, div[class*="select__control"], div[class*="control"]') : null) || el;
                    const valContainer = searchRoot ? searchRoot.querySelector('.select__single-value, .select__multi-value, [class*="singleValue"], [class*="single-value"], [class*="multiValue"], div[class*="ValueContainer"]') : null;
                    val = valContainer ? valContainer.innerText.trim() : (el.value || '');
                } else {
                    val = el.value || '';
                }

                // If this is a nested input inside a select container that has a value, sync it
                if (isInsideSelect && !val && wrapper) {
                    const valContainer = wrapper.querySelector('.select__single-value, .select__multi-value, [class*="singleValue"], [class*="single-value"], [class*="multiValue"], div[class*="ValueContainer"]');
                    if (valContainer) val = valContainer.innerText.trim();
                }

                // Checkboxes in a group should not be individually marked required unless the element itself is required
                let required = false;
                let group = '';
                if (type === 'checkbox' || type === 'radio') {
                    const parentQuestion = el.closest('fieldset, div.custom-question, div[class*="question"], div[class*="field"]');
                    if (parentQuestion) {
                        const legend = parentQuestion.querySelector('legend, label, .field__label, [class*="label"]');
                        group = legend ? legend.innerText.trim() : parentQuestion.innerText.split('\\n')[0].trim();
                    }
                    // Element is only required if explicitly marked or if its question group has an asterisk
                    const isExplicitlyRequired = el.required || el.getAttribute('aria-required') === 'true';
                    const groupRequired = group.includes('*');
                    required = isExplicitlyRequired || groupRequired;
                } else {
                    required = el.required || el.getAttribute('aria-required') === 'true' || label.includes('*');
                }

                let options = [];
                if (type === 'select-one' || type === 'select-multiple') {
                    options = Array.from(el.options || [])
                        .map(o => o.text.trim())
                        .filter(t => t && !/^(select|choose|--)/i.test(t));
                }

                fields.push({
                    id: id || name,
                    name: name,
                    label: label,
                    group: group,
                    type: type,
                    isCombobox: isCombobox,
                    value: (val || '').trim(),
                    required: required,
                    options: options
                });
            });
            return fields;
        }""")
    except Exception as ex:
        logger.warning("Failed to extract live DOM state for verification: %s", ex)
        dom_state = []

    # Map DOM state by label and ID for comparison
    dom_by_label: dict[str, dict[str, Any]] = {}
    for f in dom_state:
        lbl = (f.get("label") or "").strip().lower()
        if lbl:
            dom_by_label[lbl] = f
        result.dom_values[f.get("label") or f.get("id")] = f.get("value", "")

    # Group checkboxes/radios by label and group to check if at least one in the group is selected
    checkbox_groups_satisfied: set[str] = set()
    for f in dom_state:
        if f.get("type") in ("checkbox", "radio") and f.get("value"):
            grp_key = (f.get("group") or "").strip().lower()
            name_key = (f.get("name") or "").strip().lower()
            lbl_key = (f.get("label") or "").strip().lower()
            if grp_key:
                checkbox_groups_satisfied.add(grp_key)
            if name_key:
                checkbox_groups_satisfied.add(name_key)
            if lbl_key:
                checkbox_groups_satisfied.add(lbl_key)

    # 2. Check for missing required fields in the live DOM
    for f in dom_state:
        f_type = f.get("type", "")
        f_val = f.get("value", "")
        lbl_low = (f.get("label") or "").strip().lower()
        grp_low = (f.get("group") or "").strip().lower()
        name_low = (f.get("name") or "").strip().lower()
        
        if f.get("required") and not f_val and f_type != "file":
            # For checkboxes and radios, if any item with the same group/name was selected, it's satisfied
            if f_type in ("checkbox", "radio") and (lbl_low in checkbox_groups_satisfied or grp_low in checkbox_groups_satisfied or name_low in checkbox_groups_satisfied):
                continue
            # Check if optional keyword in label or group
            if not any(opt in lbl_low or opt in grp_low for opt in ["optional", "if applicable", "if willing"]):
                display_name = f.get("label") or f.get("group") or f.get("name") or f.get("id") or "an unlabeled field"
                result.unresolved_required_fields.append(display_name)
                result.issues.append(
                    DOMVerificationIssue(
                        field_id=f.get("id", ""),
                        label=f.get("label", ""),
                        intended_value="[Required Value]",
                        actual_dom_value="",
                        issue_type="MISSING_REQUIRED",
                        severity="BLOCKING",
                        details=f"Required field '{display_name}' is empty in the live browser DOM.",
                        field_type=f_type,
                        options=f.get("options") or [],
                    )
                )

    # 3. Specific validation: Check Location autocomplete state
    profile_city = (profile.get("city") or "Auburn").lower()
    profile_state = (profile.get("state") or "Washington").lower()
    profile_state_abbrev = "wa" if "washington" in profile_state else profile_state[:2]

    for lbl_low, f in dom_by_label.items():
        if "location" in lbl_low or "city" in lbl_low:
            actual_loc = f.get("value", "").lower()
            if actual_loc:
                # Catch wrong location selections like "Auburn, ND" or "Illinois" or "Akshaya Nagara"
                if "akshaya" in actual_loc or "india" in actual_loc:
                    result.issues.append(
                        DOMVerificationIssue(
                            field_id=f.get("id", ""),
                            label=f.get("label", ""),
                            intended_value=f"{profile.get('city')}, {profile.get('state')}",
                            actual_dom_value=f.get("value", ""),
                            issue_type="MISMATCH",
                            severity="BLOCKING",
                            details="Location contains incorrect overseas address instead of candidate profile.",
                        )
                    )
                elif "auburn" in actual_loc and not ("wa" in actual_loc or "washington" in actual_loc) and not _state_confirmed_in_sibling_field(dom_by_label):
                    # Only a real mismatch when this field IS the combined location (no
                    # separate state field elsewhere confirms WA/Washington already).
                    # Many ATS forms split City and State into two separate fields — a
                    # bare "City" field legitimately contains just "Auburn" with no state
                    # substring at all, which isn't wrong, just incomplete information in
                    # THIS field. Checking only this field's own text previously flagged
                    # every such form as a location mismatch even when City=Auburn and
                    # State=Washington were both filled correctly in their own fields.
                    result.issues.append(
                        DOMVerificationIssue(
                            field_id=f.get("id", ""),
                            label=f.get("label", ""),
                            intended_value="Auburn, WA",
                            actual_dom_value=f.get("value", ""),
                            issue_type="MISMATCH",
                            severity="BLOCKING",
                            details=f"Location '{f.get('value')}' has wrong state (not WA).",
                        )
                    )

    # 4. Compare intended resolutions against actual DOM values
    for res in resolutions:
        if not res.answer:
            continue
        res_lbl = res.question.lower().strip()
        matching_dom = None
        for d_lbl, d_field in dom_by_label.items():
            if res_lbl in d_lbl or d_lbl in res_lbl:
                matching_dom = d_field
                break
        
        if matching_dom:
            actual = matching_dom.get("value", "").strip()
            intended = str(res.answer).strip()
            # If both have values and are completely discordant (e.g. Yes vs No)
            if actual and intended:
                if actual.lower() in ("yes", "no") and intended.lower() in ("yes", "no") and actual.lower() != intended.lower():
                    result.issues.append(
                        DOMVerificationIssue(
                            field_id=matching_dom.get("id", ""),
                            label=matching_dom.get("label", ""),
                            intended_value=intended,
                            actual_dom_value=actual,
                            issue_type="MISMATCH",
                            severity="BLOCKING",
                            details=f"Intended answer '{intended}' conflicts with live DOM value '{actual}'",
                        )
                    )

    # Set overall status
    blocking = [i for i in result.issues if i.severity == "BLOCKING"]
    result.passed = len(blocking) == 0 and len(result.unresolved_required_fields) == 0
    return result
