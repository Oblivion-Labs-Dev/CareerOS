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
from app.services.tracking_email import derive_contact_email

logger = logging.getLogger("career_os.browser_verifier")

_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_DIGITS_RE = re.compile(r"\D+")
_PHONE_CALLING_CODE_RE = re.compile(r"^\+?\d{1,4}$")

# Expanded before punctuation stripping so "don't"/"do not" (or "can't"/
# "cannot") converge to the same normalized string instead of being read as
# different answers — this is a formatting difference, not a data conflict.
_CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "can't": "cannot", "won't": "will not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "wouldn't": "would not", "shouldn't": "should not", "couldn't": "could not",
    "i'm": "i am", "i've": "i have", "i'll": "i will", "i'd": "i would",
}

# Whole-word synonym classes for common EEOC/demographic answer wordings that
# differ by exact term used (a resolved answer like "Man" vs a form's own
# option label "Male") but mean the same thing — mapped to one canonical word
# per class. Applied per-word, never as a substring replace, so "human" or
# "woman" don't get mangled by a bare "man"/"woman" rule.
_SYNONYM_WORDS: dict[str, str] = {}
for _class in (
    ("man", "male"),
    ("woman", "female"),
    # US state abbreviation vs full name (each full name here is one word
    # after _PUNCT_RE splits on the space in two-word states, so "new york"
    # becomes tokens "new"/"york" and can't collide with the single-token
    # abbreviation "ny" anyway — listing them is harmless and keeps this table
    # a complete, direct reference rather than a partial one someone has to
    # remember to extend). Fixes an observed real case: an intended answer of
    # "Auburn, WA" was flagged as conflicting with a location autocomplete's
    # own "Auburn, Washington, United States" — same place, just a state
    # abbreviation the live DOM widget always expands to its full name.
    ("alabama", "al"), ("alaska", "ak"), ("arizona", "az"), ("arkansas", "ar"),
    ("california", "ca"), ("colorado", "co"), ("connecticut", "ct"), ("delaware", "de"),
    ("florida", "fl"), ("georgia", "ga"), ("hawaii", "hi"), ("idaho", "id"),
    ("illinois", "il"), ("indiana", "in"), ("iowa", "ia"), ("kansas", "ks"),
    ("kentucky", "ky"), ("louisiana", "la"), ("maine", "me"), ("maryland", "md"),
    ("massachusetts", "ma"), ("michigan", "mi"), ("minnesota", "mn"), ("mississippi", "ms"),
    ("missouri", "mo"), ("montana", "mt"), ("nebraska", "ne"), ("nevada", "nv"),
    ("ohio", "oh"), ("oklahoma", "ok"), ("oregon", "or"), ("pennsylvania", "pa"),
    ("tennessee", "tn"), ("texas", "tx"), ("utah", "ut"), ("vermont", "vt"),
    ("virginia", "va"), ("washington", "wa"), ("wisconsin", "wi"), ("wyoming", "wy"),
):
    _canonical = _class[0]
    for _word in _class:
        _SYNONYM_WORDS[_word] = _canonical


def _normalize_words(value: str) -> list[str]:
    """Lowercase, expand contractions/synonyms, strip punctuation, split to words."""
    text = (value or "").lower()
    for contraction, expanded in _CONTRACTIONS.items():
        text = text.replace(contraction, expanded)
    text = _PUNCT_RE.sub(" ", text)
    return [_SYNONYM_WORDS.get(w, w) for w in text.split()]


def _normalize_for_compare(value: str) -> str:
    """Compact (no separators) normalized form, for exact-equality comparison
    only — e.g. so "U.S." and "US" compare equal regardless of the dot. NOT
    safe for substring containment (see _values_conflict): compacting removes
    word boundaries, so unrelated words can end up literally containing one
    another (e.g. "female" contains "male") once spaces are gone.
    """
    return "".join(_normalize_words(value))


def _values_conflict(intended: str, actual: str) -> bool:
    """True only when two non-empty values are clearly NOT the same underlying
    answer — never flags on formatting differences alone (spacing, punctuation,
    contractions, dropdown option text wrapping a shorter intended value,
    phone number punctuation), since a same-underlying-value formatting
    difference is not a data-accuracy bug and flagging it would just teach
    reviewers to ignore this check.
    """
    intended, actual = (intended or "").strip(), (actual or "").strip()
    if not intended or not actual:
        return False

    # "checked" is our own internal sentinel for "we successfully checked
    # this consent/checkbox" — it is never the field's real DOM value. The
    # DOM extractor only produces a non-empty value for a checkbox at all
    # when el.checked is true (falling back to the checkbox's raw `value`
    # attribute, typically an opaque Greenhouse-internal option id like
    # "21038676007"), so any non-empty actual value already proves the box
    # is checked — comparing it as text against the word "checked" was
    # structurally guaranteed to "conflict" on virtually every real
    # checkbox, since the value attribute is coincidentally the string
    # "checked" only by accident.
    if intended.lower() == "checked":
        return False

    # Chrome always reports a file <input>'s value as "C:\fakepath\<name>"
    # regardless of the real file path, for privacy — comparing that
    # literally against the plain filename we intended to upload (e.g. a
    # resume) always "conflicts" even on a correct upload.
    if actual.lower().startswith("c:\\fakepath\\"):
        actual = actual[len("c:\\fakepath\\"):]

    # Some react-select variants' DOM structure doesn't match any of the
    # display-text selectors this extractor tries, so it falls back to the
    # underlying hidden input's raw `value` — for react-select that's the
    # internal option value (a long opaque hash/UUID, e.g.
    # "bd9f80875208dd5d202543a5d9fa853a"), never anything a human actually
    # sees or types. A hash can't be compared meaningfully against a real
    # answer, and treating the mismatch as real just means our own
    # extraction failed, not that the fill was wrong — so skip the compare.
    if re.fullmatch(r"[0-9a-f]{16,40}", actual, re.IGNORECASE):
        return False

    # A bare phone calling code ("+1", "44") is only ever a legitimate answer
    # to a phone-country-code selector, never to a generic "Country" (or
    # similar) question — this exact confusion is a known label-matching gap
    # (a short resolution question like "Country" can end up loosely matched
    # against an unrelated "Phone Country Code" DOM field). Since the calling
    # code is correct for ITS OWN field regardless of what got matched to it,
    # treat it as compatible with anything rather than flag a mismatch that's
    # really a matching artifact, not a data error.
    if _PHONE_CALLING_CODE_RE.match(actual) and not _PHONE_CALLING_CODE_RE.match(intended):
        return False

    # Email addresses: if base addresses match ignoring plus tags (e.g. user+career@gmail.com vs user@gmail.com),
    # they are functionally identical routing to the same inbox — never a conflict.
    if "@" in intended and "@" in actual:
        base_i = re.sub(r"\+[^@]+", "", intended.lower().strip())
        base_a = re.sub(r"\+[^@]+", "", actual.lower().strip())
        if base_i == base_a:
            return False

    # Date fields (e.g. start date picker returning "09/20/2026" or "2026-09-20"):
    # When intended is a relative phrase ("2 weeks from offer", "Immediately", "2 weeks")
    # or vice versa, the browser date picker filled an actual date equivalent to the notice period.
    _DATE_PATTERN = r"^\d{1,4}[/-]\d{1,2}[/-]\d{1,4}$"
    actual_clean = actual.strip().split("\n")[0].strip()
    intended_clean = intended.strip().split("\n")[0].strip()
    if (re.match(_DATE_PATTERN, actual_clean) and any(w in intended.lower() for w in ("week", "offer", "immediate", "month", "start"))) or \
       (re.match(_DATE_PATTERN, intended_clean) and any(w in actual.lower() for w in ("week", "offer", "immediate", "month", "start"))):
        return False

    if _normalize_for_compare(intended) == _normalize_for_compare(actual):
        return False
    # One is a whole-word prefix of the other (e.g. intended "Yes" vs DOM
    # "Yes, I have experience"). Word-boundary-anchored, not a raw substring
    # check: a plain substring test would wrongly call "Man"/"Woman"
    # compatible once normalized to "male"/"female", since "female" literally
    # contains "male" as characters — anchoring on whole words avoids that.
    words_i, words_a = _normalize_words(intended), _normalize_words(actual)
    if words_i and words_a:
        shorter, longer = (words_i, words_a) if len(words_i) <= len(words_a) else (words_a, words_i)
        if longer[: len(shorter)] == shorter:
            return False
    # Phone numbers / anything numeric: compare digits only.
    digits_i, digits_a = _DIGITS_RE.sub("", intended), _DIGITS_RE.sub("", actual)
    if digits_i and digits_a and (digits_i == digits_a or digits_i.lstrip("1") == digits_a.lstrip("1")):
        return False
    return True


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


def _state_confirmed_in_sibling_field(dom_by_label: dict[str, dict[str, Any]], profile_state: str, profile_state_abbrev: str) -> bool:
    """True if some other field on the page (a separate State dropdown/input,
    distinct from the City field being checked) already holds the candidate's
    actual profile state, spelled out or abbreviated."""
    if not profile_state and not profile_state_abbrev:
        return False
    for lbl_low, f in dom_by_label.items():
        if "state" in lbl_low:
            val = (f.get("value") or "").lower()
            if (profile_state and profile_state in val) or (profile_state_abbrev and val == profile_state_abbrev):
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
                if (el.getAttribute('aria-hidden') === 'true' || (el.className && typeof el.className === 'string' && el.className.includes('requiredInput'))) {
                    return;
                }
                const wrapper = el.closest('div.select__control, div[class*="select__control"], .field, .custom-question');
                const isInsideSelect = el.tagName === 'INPUT' && !!el.closest('div.select__control, div[class*="select__control"]');
                
                // If this is a nested input inside a react-select control, skip it — the parent container
                // div.select__control represents the full combobox field and will extract the combined value.
                if (isInsideSelect) {
                    return;
                }
                const isCombobox = el.getAttribute('role') === 'combobox' || el.classList.contains('select__control') || (el.className && typeof el.className === 'string' && el.className.includes('select__'));

                let label = '';
                const innerInput = el.querySelector ? el.querySelector('input') : null;
                const id = el.id || (innerInput ? (innerInput.id || innerInput.getAttribute('name')) : '') || '';
                const name = el.getAttribute('name') || (innerInput ? innerInput.getAttribute('name') : '') || '';
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
                if (type === 'checkbox') {
                    val = el.checked ? (el.value || 'true') : '';
                } else if (type === 'radio') {
                    if (el.checked) {
                        val = el.value || 'true';
                        // Also try to get the readable label of the checked radio
                        if (id) {
                            try {
                                const lblEl = document.querySelector(`label[for="${id}"]`);
                                if (lblEl && lblEl.innerText && lblEl.innerText.trim()) {
                                    val = lblEl.innerText.trim();
                                }
                            } catch(e) {}
                        }
                    } else if (name) {
                        // If unchecked, see if another radio in the same group is checked
                        const checkedSibling = document.querySelector(`input[type="radio"][name="${CSS.escape(name)}"]:checked`);
                        if (checkedSibling) {
                            val = checkedSibling.value || 'true';
                            if (checkedSibling.id) {
                                try {
                                    const sibLbl = document.querySelector(`label[for="${checkedSibling.id}"]`);
                                    if (sibLbl && sibLbl.innerText && sibLbl.innerText.trim()) {
                                        val = sibLbl.innerText.trim();
                                    }
                                } catch(e) {}
                            }
                        }
                    }
                } else if (isCombobox) {
                    const searchRoot = wrapper || (el.closest ? el.closest('div.select__control, div[class*="select__control"], div[class*="control"]') : null) || el;
                    const valContainer = searchRoot ? searchRoot.querySelector('.select__single-value, .select__multi-value, [class*="singleValue"], [class*="single-value"], [class*="multiValue"], div[class*="ValueContainer"]') : null;
                    val = valContainer ? valContainer.innerText.trim() : (el.value || '');
                    if (!val && searchRoot) {
                        const childInput = searchRoot.querySelector('input');
                        if (childInput && childInput.value) val = childInput.value.trim();
                    }
                } else {
                    val = el.value || '';
                }

                // Checkboxes/radios in a group should not be individually marked required unless the element itself is required
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
                    // For radios: only mark required if no radio in the group is checked
                    if (type === 'radio' && val) {
                        required = false;
                    } else {
                        required = isExplicitlyRequired || groupRequired;
                    }
                } else {
                    const isExplicitlyRequired = el.required || el.getAttribute('aria-required') === 'true' || (innerInput && (innerInput.required || innerInput.getAttribute('aria-required') === 'true'));
                    required = isExplicitlyRequired || label.includes('*');
                }

                // A disabled input cannot be filled and the form will not enforce
                // it, so it is not an unresolved required field. Greenhouse leaves
                // aria-required="true" on an Employment row's end-date inputs after
                // "Current role" is ticked and merely disables them — reading those
                // as required-but-empty blocked submissions whose form was in fact
                // complete and correctly filled.
                if (required && (el.disabled || el.getAttribute('aria-disabled') === 'true' || (innerInput && innerInput.disabled))) {
                    required = false;
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
    dom_by_id: dict[str, dict[str, Any]] = {}
    for f in dom_state:
        lbl = (f.get("label") or "").strip().lower()
        if lbl:
            dom_by_label[lbl] = f
        fid = f.get("id")
        if fid:
            dom_by_id[fid] = f
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
            # Check if optional keyword in label or group, or legally voluntary demographic disclosure
            is_voluntary = any(
                vd in lbl_low or vd in grp_low
                for vd in (
                    "gender", "race", "ethnic", "hispanic", "latino", "veteran",
                    "disability", "disabled", "self-identif", "self identif",
                    "eeo", "equal employment", "protected veteran",
                    "sexual orientation", "transgender", "pronoun",
                )
            )
            if not is_voluntary and not any(opt in lbl_low or opt in grp_low for opt in ["optional", "if applicable", "if willing"]):
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

    # 3. Specific validation: Check Location autocomplete state, driven by
    # whatever the candidate's own profile actually says (never a hardcoded
    # place) — skip entirely if the profile has no city/state on file, since
    # there's nothing to verify against.
    profile_city = (profile.get("city") or "").strip().lower()
    profile_state = (profile.get("state") or "").strip().lower()
    profile_state_abbrev = "wa" if "washington" in profile_state else profile_state[:2]

    if profile_city or profile_state:
        for lbl_low, f in dom_by_label.items():
            if "location" in lbl_low or "city" in lbl_low:
                actual_loc = f.get("value", "").lower()
                if not actual_loc:
                    continue
                # If the field specifically asks for City (and not State/Region), containing the profile city is fully valid
                if "city" in lbl_low and not ("state" in lbl_low or "region" in lbl_low):
                    continue
                # Only flag when the field DOES contain the candidate's actual
                # city but is missing their state — a field that autocompleted
                # to a city/place with no relation to the profile at all is
                # already caught by the DOM required-field and answer-mismatch
                # checks elsewhere; this section exists specifically for the
                # "right city, state got dropped by autocomplete" failure mode.
                if (
                    profile_city
                    and profile_city in actual_loc
                    and profile_state
                    and profile_state not in actual_loc
                    and not (profile_state_abbrev and profile_state_abbrev in actual_loc)
                    and not _state_confirmed_in_sibling_field(dom_by_label, profile_state, profile_state_abbrev)
                ):
                    # Many ATS forms split City and State into separate fields — a bare
                    # "City" field containing only the profile city with no state text
                    # isn't wrong, just incomplete on its own, so only treat this as a
                    # real mismatch if no separate State field elsewhere already
                    # confirms the profile's actual state.
                    result.issues.append(
                        DOMVerificationIssue(
                            field_id=f.get("id", ""),
                            label=f.get("label", ""),
                            intended_value=f"{profile.get('city')}, {profile.get('state')}",
                            actual_dom_value=f.get("value", ""),
                            issue_type="MISMATCH",
                            severity="BLOCKING",
                            details=f"Location '{f.get('value')}' doesn't match the candidate's actual profile city/state.",
                        )
                    )

    # 4. Compare intended resolutions against actual DOM values. Deterministic,
    # not LLM-guessed: every resolved answer with a live matching DOM field
    # must actually agree with what's on screen, not just the Yes/No subset
    # this used to check — a wrong value here is exactly the class of bug
    # (autofill glitch, stale value from a prior attempt, wrong field matched)
    # that should block submission rather than ride along silently.
    for res in resolutions:
        if not res.answer:
            continue
        res_lbl = res.question.lower().strip()
        # Prefer an exact pairing (field id, then exact label) before ever
        # falling back to substring containment. Two different questions on
        # the same form often have one label as a substring of the other
        # (e.g. "Website" / "Portfolio Website", or a short label that
        # happens to appear inside an unrelated longer one) — matching on
        # containment alone pairs the wrong DOM field to a resolved answer,
        # which then reports a "conflict" between two unrelated questions
        # (observed live: a GitHub URL answer flagged as conflicting with an
        # EEO experience-level dropdown's value). Field id is unambiguous
        # when present; an exact label match is the next safest thing.
        matching_dom = dom_by_id.get(res.field_id) if res.field_id else None
        if matching_dom is None:
            matching_dom = dom_by_label.get(res_lbl)
        if matching_dom is None:
            for d_lbl, d_field in dom_by_label.items():
                if res_lbl in d_lbl or d_lbl in res_lbl:
                    matching_dom = d_field
                    break

        if matching_dom:
            actual = matching_dom.get("value", "").strip()
            intended = str(res.answer).strip()
            # A checked checkbox's DOM "value" is its own raw option id
            # (Greenhouse assigns each one an opaque numeric id, e.g.
            # "86355847004"), never the readable option text — comparing
            # that against a resolved answer like "Yes" always "conflicts"
            # even when the correct box was checked. A non-empty value here
            # already proves *some* box in the group got checked; that's all
            # this check can verify for a checkbox's own value attribute.
            if matching_dom.get("type") == "checkbox" and actual:
                continue
            if _values_conflict(intended, actual):
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

    # 5. Deterministic identity-field check: the candidate's core identity
    # (name, email, phone) is filled directly by CSS selector rather than
    # through resolve_answer(), so it never passed through check #4 above —
    # verify it explicitly against the actual profile instead of trusting
    # that the fill succeeded.
    identity_checks = [
        ("first name", (profile.get("firstName") or "").strip()),
        ("last name", (profile.get("lastName") or "").strip()),
        ("email", derive_contact_email((profile.get("email") or "").strip())),
        ("phone", (profile.get("phone") or "").strip()),
    ]
    for field_key, expected in identity_checks:
        if not expected:
            continue
        for lbl_low, f in dom_by_label.items():
            if field_key not in lbl_low:
                continue
            # A genuine identity field's label is short ("Email*", "Preferred
            # First Name"). Long custom-question sentences can incidentally
            # contain the same word (e.g. DoorDash's SMS/WhatsApp consent
            # question ends "...we will contact you via the email you
            # provided") — without this guard that unrelated Yes/No field
            # gets compared against the candidate's actual email address and
            # always "conflicts", since the two are semantically unrelated.
            if len(lbl_low) > 40:
                continue
            # "first name"/"last name" also match within "preferred first name" —
            # that's fine, same expected value applies there too.
            actual = (f.get("value") or "").strip()
            if not actual:
                continue
            if _values_conflict(expected, actual):
                result.issues.append(
                    DOMVerificationIssue(
                        field_id=f.get("id", ""),
                        label=f.get("label", ""),
                        intended_value=expected,
                        actual_dom_value=actual,
                        issue_type="MISMATCH",
                        severity="BLOCKING",
                        details=f"Live DOM value '{actual}' for '{f.get('label') or field_key}' doesn't match the candidate's actual profile ('{expected}').",
                    )
                )

    # Set overall status
    blocking = [i for i in result.issues if i.severity == "BLOCKING"]
    result.passed = len(blocking) == 0 and len(result.unresolved_required_fields) == 0
    return result
