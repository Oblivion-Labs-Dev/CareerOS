"""ATS Autofill Plugin Reference Module for CareerOS Automation.

Direct Python translation and reference of:
- apps/extension/src/adapters/atsAutofillConfig.ts
- apps/extension/src/content/fieldClassifier.ts
- apps/extension/src/content/autofillEngine.matching.ts
- apps/extension/src/shared/applicationDefaults.ts
- apps/extension/src/shared/usStates.ts
"""

from __future__ import annotations

import re
from typing import Any


# ─── 1. APPLICATION FIELD DEFAULTS (from applicationDefaults.ts) ─────────────

APPLICATION_FIELD_DEFAULTS: dict[str, str] = {
    "gender": "Prefer not to answer",
    "transgender": "Prefer not to answer",
    "sexualOrientation": "Prefer not to answer",
    "raceEthnicity": "Prefer not to answer",
    "hispanic": "Prefer not to answer",
    "veteran": "I am not a protected veteran",
    "disability": "No, I don't have a disability",
    "smsConsent": "No - I do not consent to receiving text messages",
    "pronouns": "Prefer not to say",
    "phoneCountryCode": "+1",
}


# ─── 2. SYNONYMS & OPTION MATCHING (from autofillEngine.matching.ts) ─────────

SYNONYMS: dict[str, list[str]] = {
    "united states": ["us", "usa", "united states of america", "u.s.a.", "u.s.", "+1"],
    "united kingdom": ["uk", "u.k.", "great britain", "gb"],
    "yes": ["y", "true", "authorized", "checked", "agree", "allow"],
    "no": ["n", "false", "denied", "disagree", "non hispanic", "not hispanic/latino", "not hispanic"],
    "prefer not to answer": [
        "choose not to disclose",
        "i don't wish to answer",
        "i do not wish to answer",
        "decline to self-identify",
        "decline to self identify",
        "decline to answer",
        "prefer not to say",
        "do not wish to answer",
        "i prefer not to say",
        "i prefer not to answer",
    ],
    "i am not a protected veteran": [
        "not a protected veteran",
        "non veteran",
        "non-veteran",
        "i am not a protected veteran.",
        "i am not a veteran",
        "not a veteran",
        "i do not identify as a protected veteran",
        "no, i am not a protected veteran",
        "no military service",
        "i identify as one or more of the classifications of protected veteran: no",
        "no",
    ],
    "no, i don't have a disability": [
        "i don't have a disability",
        "no disability",
        "do not have a disability",
        "no, i do not have a disability and have not had one in the past",
        "no, i do not have a disability and have not had one in the past.",
        "no, i do not have a disability, or have a history/record of having a disability",
        "no, i do not have a disability",
        "no",
    ],
    "male": ["man", "cisgender man", "cis male", "cis-male"],
    "man": ["male", "man", "cisgender man", "cis male", "cis-male"],
    "female": ["woman", "cisgender woman", "cis female", "cis-female"],
    "woman": ["female", "woman", "cisgender woman", "cis female", "cis-female"],
    "heterosexual": ["straight", "heterosexual", "straight / heterosexual", "straight/heterosexual"],
    "straight": ["straight", "heterosexual", "straight / heterosexual", "straight/heterosexual"],
    "not hispanic or latino": ["no", "not hispanic/latino", "not hispanic", "non hispanic", "no, i am not hispanic/latino", "no, i am not hispanic or latino"],
    "asian (not hispanic or latino)": ["south asian", "asian", "asian (including south asian, east asian, or southeast asian)"],
    "south asian": ["asian", "south asian", "asian (including south asian, east asian, or southeast asian)", "asian (not hispanic or latino)"],
    "asian": ["asian", "south asian", "asian (including south asian, east asian, or southeast asian)", "asian (not hispanic or latino)"],
    "no - i do not consent to receiving text messages": [
        "no - i do not consent",
        "do not consent to receiving text messages",
        "decline text messages",
        "no",
    ],
    "just use my name": ["prefer not to say", "prefer not to answer", "decline to answer"],
    "he/him/his": ["he him his", "him his he", "him/his/he", "he, him, his", "he/him"],
    "master's degree": ["ms/ma", "ms", "ma", "m.s.", "m.a.", "master's", "masters", "master degree", "graduate degree"],
    "bachelor's degree": ["bs/ba", "bs", "ba", "b.s.", "b.a.", "bachelor's", "bachelors", "bachelor degree", "undergraduate degree"],
    "phd": ["ph.d.", "doctorate", "doctoral degree", "phd/doctorate", "doctor of philosophy"],
    "mba": ["mba", "master of business administration"],
}

US_STATES: dict[str, str] = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa",
    "ks": "kansas", "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland",
    "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi", "mo": "missouri",
    "mt": "montana", "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio",
    "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
    "dc": "district of columbia",
}


def normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def is_prefer_not_to_answer(text: str) -> bool:
    norm = normalize_match_text(text)
    if re.search(r"prefer not to (answer|say)|choose not to disclose|don'?t wish to answer|do not wish to answer|decline to self[- ]?identify|decline to answer", norm):
        return True
    return any(norm == p or p in norm for p in SYNONYMS["prefer not to answer"])


def is_synonym_match(opt: str, val: str) -> bool:
    o = normalize_match_text(opt)
    v = normalize_match_text(val)
    if o == v:
        return True
    if is_prefer_not_to_answer(o) and is_prefer_not_to_answer(v):
        return True
    for canonical, synonyms in SYNONYMS.items():
        if o == canonical and v in synonyms:
            return True
        if v == canonical and o in synonyms:
            return True
        if o in synonyms and v in synonyms:
            return True
    shorter = o if len(o) <= len(v) else v
    longer = v if len(o) <= len(v) else o
    if len(shorter) >= 4 and shorter in longer:
        return True
    return False


def score_select_option_match(opt: str, val: str) -> int:
    o = normalize_match_text(opt)
    v = normalize_match_text(val)
    if not o or not v:
        return 0
    if o == v:
        return 100
    if is_synonym_match(o, v):
        return 90
    if o.startswith(f"{v} ") or o.startswith(f"{v} -") or o.startswith(f"{v},"):
        return 85
    if len(v) >= 4 and v in o:
        return 75
    if len(o) >= 4 and o in v:
        return 70
    return 0


def pick_best_matching_option(options: list[str], target_value: str) -> str | None:
    if not options or not target_value:
        return None
    best_opt = None
    best_score = 0
    for opt in options:
        score = score_select_option_match(opt, target_value)
        if score > best_score:
            best_score = score
            best_opt = opt
    return best_opt if best_score >= 70 else None


# ─── 3. CANONICAL PATTERNS (from fieldClassifier.ts) ─────────────────────────

CANONICAL_PATTERNS: dict[str, list[str]] = {
    "firstName": [
        r"first[\s_-]*name",
        r"^fname$",
        r"given[\s_-]*name",
        r"^given-name$",
        r"legal[\s_-]*first[\s_-]*name",
    ],
    "lastName": [
        r"last[\s_-]*name",
        r"^lname$",
        r"family[\s_-]*name",
        r"surname",
        r"^family-name$",
        r"legal[\s_-]*last[\s_-]*name",
    ],
    "fullName": [
        r"full\s*name",
        r"^name$",
        r"applicant\s*name",
        r"legal\s*name",
        r"candidate\s*name",
    ],
    "preferredName": [
        r"preferred\s*name",
        r"name\s*you\s*go\s*by",
        r"what.*call\s*you",
        r"nickname",
    ],
    "email": [r"email", r"e-mail"],
    "phone": [r"phone", r"telephone", r"mobile", r"\btel\b", r"cell"],
    "location": [
        r"location",
        r"city.*state",
        r"where.*(live|located)",
        r"residence",
        r"work location",
        r"current\s*city",
    ],
    "currentCompany": [
        r"current\s*company",
        r"present\s*employer",
        r"company\s*name",
        r"most\s+recently\s+worked",
        r"where.*most\s+recently\s+worked",
        r"recent\s+employer",
        r"last\s+(?:company|employer)",
        r"where.*you.*worked",
        r"organization",
        r"current\s*employer",
    ],
    "currentTitle": [
        r"current\s*(job\s*)?title",
        r"headline",
        r"current\s*role",
        r"most\s*recent\s*title",
        r"position\s*title",
    ],
    "address": [r"address", r"street", r"address\s*line\s*1"],
    "city": [r"\bcity\b", r"municipality"],
    "state": [r"\bstate\b", r"province", r"region", r"reside", r"which.*state"],
    "zip": [r"\bzip\b", r"postal\s*code", r"postal", r"postcode"],
    "country": [r"\bcountry\b", r"country/region", r"country\s*of\s*residence"],
    "linkedin": [r"linkedin", r"linked\s*in", r"urls\[linkedin\]"],
    "github": [r"github", r"git\s*hub", r"share.*github", r"urls\[github\]"],
    "portfolio": [r"portfolio", r"website", r"personal\s*site", r"personal\s*website", r"urls\[portfolio\]"],
    "resume": [r"resume", r"\bcv\b", r"curriculum\s*vitae", r"attach\s*resume", r"upload\s*resume"],
    "coverLetter": [r"cover\s*letter", r"writing\s*sample", r"coverletter"],
    "workAuthorization": [
        r"authorized",
        r"right\s*to\s*work",
        r"permit",
        r"eligible\s*to\s*work",
        r"legally\s*work",
        r"work\s*status",
        r"authorized\s*to\s*work",
    ],
    "sponsorship": [
        r"sponsor",
        r"visa\s*sponsorship",
        r"require\s*sponsorship",
        r"need\s*sponsorship",
        r"immigration",
        r"\bh-?1b\b",
        r"require\s*visa",
    ],
    "gender": [r"gender", r"\bsex\b"],
    "pronouns": [r"pronoun", r"preferred\s*pronoun"],
    "veteran": [r"veteran", r"military", r"armed\s*forces", r"protected\s*veteran"],
    "disability": [r"disability", r"handicap", r"physical\s*or\s*mental\s*impairment"],
    "raceEthnicity": [r"please\s*identify\s*your\s*race", r"\brace\b", r"ethnicity"],
    "hispanic": [r"hispanic", r"latino"],
    "smsConsent": [r"text\s*message", r"\bsms\b", r"consent.*(text|message)"],
    "salary": [r"salary", r"compensation", r"expectations", r"desired\s*pay", r"expected\s*salary", r"rate"],
    "noticePeriod": [r"notice\s*period", r"start\s*date", r"availability", r"how\s*soon\s*can\s*you\s*start"],
    "yearsExperience": [r"years\s*of\s*experience", r"experience\s*level", r"total\s*years"],
    "school": [r"school", r"university", r"college", r"institution", r"education"],
    "degree": [r"degree", r"level\s*of\s*education", r"highest\s*degree"],
    "discipline": [r"major", r"discipline", r"field\s*of\s*study"],
    "relocate": [r"relocate", r"willing\s*to\s*relocate", r"open\s*to\s*relocat"],
    "exportControl": [r"export\s*control", r"itar", r"\bear\b", r"u\.s\.\s*person", r"export\s*administration"],
    "clearanceEligibility": [r"clearance\s*eligib", r"eligibility\s*to\s*obtain.*clearance", r"able\s*to\s*obtain.*security\s*clearance"],
    "clearanceLevel": [r"clearance\s*level", r"security\s*clearance\s*held", r"current.*security\s*clearance", r"highest.*clearance"],
    "companyHistory": [r"previously\s*employed", r"have\s*you\s*ever\s*worked\s*(at|for)", r"former\s*employee", r"conflict\s*of\s*interest", r"relative.*employed"],
    "englishProficiency": [r"english\s*proficiency", r"english\s*language", r"fluent\s*in\s*english"],
    "gpa": [r"\bgpa\b", r"grade\s*point\s*average"],
    "transcript": [r"transcript", r"unofficial\s*transcript"],
    "referralSource": [r"how\s*did\s*you\s*hear", r"source", r"how\s*did\s*you\s*find\s*us"],
    "citizenship": [r"what\s*is\s*your\s*citizenship", r"your\s*citizenship", r"country\s*of\s*citizenship", r"nationality"],
    "otherLinks": [r"other\s*links", r"additional\s*links", r"other\s*url", r"supplementary\s*links"],
}


def classify_canonical_key(field_text: str) -> str | None:
    norm = normalize_match_text(field_text)
    for key, patterns in CANONICAL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, norm, re.IGNORECASE):
                return key
    return None


# ─── 4. DETERMINISTIC VALUE EXTRACTOR (from fieldClassifier.ts & profileStore.ts) ──

def extract_canonical_value(
    canonical_key: str,
    profile: dict[str, Any],
    options: list[str] | None = None,
) -> tuple[str | None, str]:
    """Resolve value for a canonical key using candidate profile and defaults.

    Returns (value, reason).
    """
    key = canonical_key

    if key == "firstName":
        val = profile.get("firstName") or (profile.get("fullName", "").split()[0] if profile.get("fullName") else None)
        return val, "Profile first name"

    if key == "lastName":
        val = profile.get("lastName") or (profile.get("fullName", "").split()[-1] if profile.get("fullName") and len(profile.get("fullName", "").split()) > 1 else None)
        return val, "Profile last name"

    if key == "fullName":
        fn = profile.get("firstName", "")
        ln = profile.get("lastName", "")
        val = f"{fn} {ln}".strip() or profile.get("fullName")
        return val, "Profile full name"

    if key == "preferredName":
        val = profile.get("preferredName") or profile.get("firstName")
        return val, "Profile preferred name"

    if key == "email":
        from app.services.tracking_email import derive_contact_email

        raw_email = profile.get("email")
        return (derive_contact_email(raw_email) if raw_email else raw_email), "Profile email"

    if key == "phone":
        return profile.get("phone"), "Profile phone"

    if key == "location":
        loc = profile.get("location") or profile.get("city")
        if loc and profile.get("state") and profile.get("state") not in loc:
            loc = f"{loc}, {profile.get('state')}"
        return loc, "Profile location"

    if key == "address":
        addr = profile.get("address") or profile.get("streetAddress") or profile.get("street")
        return addr, "Profile address"

    if key == "city":
        cf = profile.get("customFields") or {}
        city_val = profile.get("city") or cf.get("city") or profile.get("location", "").split(",")[0].strip()
        return city_val, "Profile city"

    if key == "state":
        cf = profile.get("customFields") or {}
        st = profile.get("state") or profile.get("province")
        # Resolve WA -> Washington from customFields if needed
        if not st:
            st_abbr = cf.get("state", "")
            if st_abbr:
                st = US_STATES.get(st_abbr.lower().strip(), st_abbr)
                # Capitalize properly
                st = st.title() if st else st_abbr
        if options and st:
            matched = pick_best_matching_option(options, st)
            if matched:
                return matched, "Matched state option"
        return st, "Profile state"

    if key == "zip":
        return profile.get("zip") or profile.get("postalCode") or profile.get("zipCode"), "Profile zip code"

    if key == "country":
        ctry = profile.get("country") or "United States"
        if options:
            matched = pick_best_matching_option(options, ctry)
            if matched:
                return matched, "Matched country option"
        return ctry, "Profile country"

    if key == "linkedin":
        return profile.get("linkedin") or profile.get("linkedInUrl"), "Profile LinkedIn URL"

    if key == "github":
        return profile.get("github") or profile.get("githubUrl"), "Profile GitHub URL"

    if key == "portfolio":
        return profile.get("portfolio") or profile.get("portfolioUrl") or profile.get("website"), "Profile Portfolio URL"

    if key == "currentCompany":
        comp = profile.get("currentCompany") or profile.get("employer") or profile.get("company")
        if not comp and profile.get("workExperience") and isinstance(profile.get("workExperience"), list) and len(profile["workExperience"]) > 0:
            comp = profile["workExperience"][0].get("company")
        return comp, "Candidate current company"

    if key == "currentTitle":
        title = profile.get("currentTitle") or profile.get("headline") or profile.get("title")
        if not title and profile.get("workExperience") and isinstance(profile.get("workExperience"), list) and len(profile["workExperience"]) > 0:
            title = profile["workExperience"][0].get("title")
        return title, "Candidate current title"

    if key == "resume":
        res = (
            profile.get("resumePath")
            or profile.get("resumeUrl")
            or profile.get("resumeFilename")
            or "resume.pdf"
        )
        return res, "Candidate resume document"

    if key == "coverLetter":
        cov = (
            profile.get("coverLetterPath")
            or profile.get("coverLetterUrl")
            or profile.get("coverLetterFilename")
            or "cover_letter.pdf"
        )
        return cov, "Candidate cover letter document"

    if key == "workAuthorization":
        auth = profile.get("workAuthorization")
        if auth is None:
            auth_val = "Yes"
        elif str(auth).lower() in ("yes", "true", "1", "authorized"):
            auth_val = "Yes"
        else:
            auth_val = "No"
        if options:
            matched = pick_best_matching_option(options, auth_val)
            if matched:
                return matched, "Matched work authorization option"
        return auth_val, "Candidate work authorization"

    if key == "sponsorship":
        spons = profile.get("requiresSponsorship") if profile.get("requiresSponsorship") is not None else profile.get("sponsorship")
        if spons is False or str(spons).lower() in ("no", "false", "0"):
            spons_val = "No"
        else:
            spons_val = "Yes"
        if options:
            # Only match Yes/No from available options — never append visa type details
            matched = pick_best_matching_option(options, spons_val)
            if matched:
                return matched, "Matched sponsorship option"
        return spons_val, "Candidate sponsorship requirement"

    if key == "yearsExperience":
        exp = str(profile.get("yearsExperience") or profile.get("totalExperienceYears") or "5")
        if options:
            matched = pick_best_matching_option(options, exp)
            if matched:
                return matched, "Matched years of experience option"
        return exp, "Candidate years of experience"

    if key == "salary":
        sal = profile.get("salaryExpectations") or profile.get("desiredSalary") or profile.get("salary") or "Competitive / Open"
        return str(sal), "Candidate salary expectation"

    if key == "noticePeriod":
        np = profile.get("noticePeriod") or profile.get("startDate") or "2 weeks"
        if options:
            matched = pick_best_matching_option(options, np)
            if matched:
                return matched, "Matched notice period option"
        return np, "Candidate availability"

    if key == "gender":
        g = profile.get("gender") or APPLICATION_FIELD_DEFAULTS["gender"]
        if options:
            matched = pick_best_matching_option(options, g)
            if matched:
                return matched, "Matched gender option"
        return g, "Demographic default"

    if key == "pronouns":
        p = profile.get("pronouns") or APPLICATION_FIELD_DEFAULTS["pronouns"]
        if options:
            matched = pick_best_matching_option(options, p)
            if matched:
                return matched, "Matched pronouns option"
        return p, "Demographic default"

    if key == "veteran":
        v = profile.get("veteran") or APPLICATION_FIELD_DEFAULTS["veteran"]
        if options:
            matched = pick_best_matching_option(options, v)
            if matched:
                return matched, "Matched veteran option"
        return v, "Demographic default"

    if key == "disability":
        d = profile.get("disability") or APPLICATION_FIELD_DEFAULTS["disability"]
        if options:
            matched = pick_best_matching_option(options, d)
            if matched:
                return matched, "Matched disability option"
        return d, "Demographic default"

    if key == "raceEthnicity":
        r = profile.get("raceEthnicity") or APPLICATION_FIELD_DEFAULTS["raceEthnicity"]
        if options:
            matched = pick_best_matching_option(options, r)
            if matched:
                return matched, "Matched race/ethnicity option"
        return r, "Demographic default"

    if key == "hispanic":
        h = profile.get("hispanic") or APPLICATION_FIELD_DEFAULTS["hispanic"]
        if options:
            matched = pick_best_matching_option(options, h)
            if matched:
                return matched, "Matched hispanic option"
        return h, "Demographic default"

    if key == "smsConsent":
        s = profile.get("smsConsent") or APPLICATION_FIELD_DEFAULTS["smsConsent"]
        if options:
            matched = pick_best_matching_option(options, s)
            if matched:
                return matched, "Matched SMS consent option"
        return s, "SMS consent default"

    if key == "school":
        sch = profile.get("school") or profile.get("university") or profile.get("college")
        if not sch and profile.get("education") and isinstance(profile.get("education"), list) and len(profile["education"]) > 0:
            sch = profile["education"][0].get("school")
        return sch, "Candidate education institution"

    if key == "degree":
        deg = profile.get("degree")
        if not deg and profile.get("education") and isinstance(profile.get("education"), list) and len(profile["education"]) > 0:
            deg = profile["education"][0].get("degree")
        if options and deg:
            matched = pick_best_matching_option(options, deg)
            if matched:
                return matched, "Matched degree option"
        return deg or "Bachelor's Degree", "Candidate degree"

    if key == "relocate":
        rel = profile.get("relocate", "Yes")
        if options:
            matched = pick_best_matching_option(options, str(rel))
            if matched:
                return matched, "Matched relocation option"
        return "Yes", "Relocation preference"

    if key == "exportControl":
        val = "None of the above"
        if options:
            matched = pick_best_matching_option(options, "None of the above") or pick_best_matching_option(options, "No") or pick_best_matching_option(options, "None")
            if matched:
                return matched, "Matched export control option"
        return val, "Export control authorization"

    if key == "clearanceEligibility":
        if options:
            matched = pick_best_matching_option(options, "No") or pick_best_matching_option(options, "Not eligible")
            if matched:
                return matched, "Matched clearance eligibility"
        return "No", "Clearance eligibility default"

    if key == "clearanceLevel":
        cl = profile.get("clearanceLevel") or "None"
        if options:
            matched = pick_best_matching_option(options, cl) or pick_best_matching_option(options, "None")
            if matched:
                return matched, "Matched clearance level"
        return cl, "Candidate clearance level"

    if key == "companyHistory":
        val = "No"
        if options:
            matched = pick_best_matching_option(options, "No")
            if matched:
                return matched, "Matched employment history option"
        return val, "Prior company affiliation default"

    if key == "englishProficiency":
        val = "Fluent"
        if options:
            matched = pick_best_matching_option(options, "Fluent") or pick_best_matching_option(options, "Professional") or pick_best_matching_option(options, "Native")
            if matched:
                return matched, "Matched English proficiency option"
        return val, "English proficiency default"

    if key == "gpa":
        val = str(profile.get("gpa") or "3.5")
        if options:
            matched = pick_best_matching_option(options, val) or pick_best_matching_option(options, "3.5") or pick_best_matching_option(options, "3.0")
            if matched:
                return matched, "Matched GPA option"
        return val, "Candidate GPA"

    if key == "transcript":
        val = "Yes"
        if options:
            matched = pick_best_matching_option(options, "Yes") or pick_best_matching_option(options, "Official") or pick_best_matching_option(options, "Unofficial")
            if matched:
                return matched, "Transcript option default"
        return val, "Transcript default"

    if key == "referralSource":
        val = "LinkedIn"
        if options:
            matched = pick_best_matching_option(options, "LinkedIn") or pick_best_matching_option(options, "Job Board") or pick_best_matching_option(options, "Other")
            if matched:
                return matched, "Matched referral source option"
        return val, "Referral source default"

    if key == "citizenship":
        cit = profile.get("citizenship") or "India"
        if options:
            matched = pick_best_matching_option(options, cit)
            if matched:
                return matched, "Matched citizenship option"
        return cit, "Candidate citizenship"

    if key == "otherLinks":
        # "Other Links" should be a URL (portfolio, GitHub), not a prose answer
        val = profile.get("portfolio") or profile.get("portfolioUrl") or profile.get("website") or profile.get("github") or ""
        return val, "Candidate other links (URL)"

    return None, ""


# ─── 5. ATS AUTOFILL PIPELINE CONFIGS (from atsAutofillConfig.ts) ───────────

ATS_CONFIGS: dict[str, dict[str, Any]] = {
    "greenhouse": {
        "id": "greenhouse",
        "name": "Greenhouse",
        "hostPatterns": [r"greenhouse\.io", r"gh_jid="],
        "fieldSteps": [
            {"field": "resume", "selector": "input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "input[name=\"job_application[first_name]\"], input[name*=\"first_name\"], #first_name", "method": "text", "required": True},
            {"field": "lastName", "selector": "input[name=\"job_application[last_name]\"], input[name*=\"last_name\"], #last_name", "method": "text", "required": True},
            {"field": "email", "selector": "input[name=\"job_application[email]\"], input[type=\"email\"], input[name*=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[name=\"job_application[phone]\"], input[type=\"tel\"], input[name*=\"phone\"]", "method": "text", "required": True},
            {"field": "linkedin", "selector": "input[name*=\"linkedin\"], input[id*=\"linkedin\"]", "method": "text", "required": False},
            {"field": "coverLetter", "selector": "input[type=\"file\"][name*=\"cover\"], textarea[name*=\"cover\"]", "method": "uploadCoverLetter", "required": False},
        ],
    },
    "lever": {
        "id": "lever",
        "name": "Lever",
        "hostPatterns": [r"jobs\.(eu\.)?lever\.co"],
        "fieldSteps": [
            {"field": "resume", "selector": "#resume-upload-input, input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "fullName", "selector": "input[name=\"name\"], input[data-qa=\"name-input\"]", "method": "text", "required": True},
            {"field": "email", "selector": "input[name=\"email\"], input[type=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[name=\"phone\"], input[type=\"tel\"]", "method": "text", "required": True},
            {"field": "currentCompany", "selector": "input[name=\"org\"], input[name*=\"company\"]", "method": "text", "required": False},
            {"field": "linkedin", "selector": "input[name*=\"urls[LinkedIn]\"], input[name*=\"linkedin\"]", "method": "text", "required": False},
            {"field": "github", "selector": "input[name*=\"urls[GitHub]\"], input[name*=\"github\"]", "method": "text", "required": False},
            {"field": "portfolio", "selector": "input[name*=\"urls[Portfolio]\"], input[name*=\"portfolio\"]", "method": "text", "required": False},
        ],
    },
    "ashby": {
        "id": "ashby",
        "name": "Ashby",
        "hostPatterns": [r"jobs\.ashbyhq\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": ".fieldEntry input[type=\"file\"][accept*=\"pdf\"], input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "input[name*=\"first\"], input[autocomplete=\"given-name\"]", "method": "text", "required": True},
            {"field": "lastName", "selector": "input[name*=\"last\"], input[autocomplete=\"family-name\"]", "method": "text", "required": True},
            {"field": "email", "selector": "input[type=\"email\"], input[name*=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[type=\"tel\"], input[name*=\"phone\"]", "method": "text", "required": True},
            {"field": "linkedin", "selector": "input[name*=\"linkedin\"], input[placeholder*=\"linkedin\" i]", "method": "text", "required": False},
        ],
    },
    "workday": {
        "id": "workday",
        "name": "Workday",
        "hostPatterns": [r"myworkdayjobs\.com", r"myworkdaysite\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": "[data-automation-id=\"file-upload-input-ref\"], input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "[data-automation-id=\"firstName\"], [data-automation-id=\"legalNameSection_firstName\"]", "method": "text", "required": True},
            {"field": "lastName", "selector": "[data-automation-id=\"lastName\"], [data-automation-id=\"legalNameSection_lastName\"]", "method": "text", "required": True},
            {"field": "email", "selector": "[data-automation-id=\"email\"], input[type=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "[data-automation-id=\"phone\"], [data-automation-id=\"phone-number\"]", "method": "text", "required": True},
            {"field": "linkedin", "selector": "[data-automation-id*=\"linkedin\" i], input[aria-label*=\"LinkedIn\" i]", "method": "text", "required": False},
        ],
    },
    "smartrecruiters": {
        "id": "smartrecruiters",
        "name": "SmartRecruiters",
        "hostPatterns": [r"smartrecruiters\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": "input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "input[name*=\"firstName\"], input[name*=\"first_name\"]", "method": "text", "required": True},
            {"field": "lastName", "selector": "input[name*=\"lastName\"], input[name*=\"last_name\"]", "method": "text", "required": True},
            {"field": "email", "selector": "input[type=\"email\"], input[name*=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[type=\"tel\"], input[name*=\"phone\"]", "method": "text", "required": True},
        ],
    },
    "workable": {
        "id": "workable",
        "name": "Workable",
        "hostPatterns": [r"apply\.workable\.com", r"jobs\.workable\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": "input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "fullName", "selector": "input[name=\"name\"], input[name*=\"fullname\"]", "method": "text", "required": True},
            {"field": "email", "selector": "input[type=\"email\"], input[name=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[type=\"tel\"], input[name=\"phone\"]", "method": "text", "required": True},
        ],
    },
    "icims": {
        "id": "icims",
        "name": "iCIMS",
        "hostPatterns": [r"icims\.com", r"jibeapply\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": "input[type=\"file\"][name*=\"resume\" i]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "#icims_f_firstName, input[autocomplete=\"given-name\"]", "method": "text", "required": True},
            {"field": "lastName", "selector": "#icims_f_lastName, input[autocomplete=\"family-name\"]", "method": "text", "required": True},
            {"field": "email", "selector": "#icims_f_email, input[autocomplete=\"email\"], input[type=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "#icims_f_mobilePhone, input[autocomplete=\"tel-national\"], input[type=\"tel\"]", "method": "text", "required": True},
        ],
    },
    "rippling": {
        "id": "rippling",
        "name": "Rippling",
        "hostPatterns": [r"ats\.rippling\.com"],
        "fieldSteps": [
            {"field": "resume", "selector": "input[type=\"file\"]", "method": "uploadResume", "required": True},
            {"field": "firstName", "selector": "input[name*=\"first\"]", "method": "text", "required": True},
            {"field": "lastName", "selector": "input[name*=\"last\"]", "method": "text", "required": True},
            {"field": "email", "selector": "input[type=\"email\"]", "method": "text", "required": True},
            {"field": "phone", "selector": "input[type=\"tel\"]", "method": "text", "required": True},
        ],
    },
}
