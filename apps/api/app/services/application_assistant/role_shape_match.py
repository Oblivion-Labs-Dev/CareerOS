"""Deterministic resume-to-job match scoring by role shape (no model).

Promoted from the matcher benchmark (``scripts/matchlab``, results in
``docs/matcher-benchmark.md``), which measured nine scorers on labelled
postings. This one won: role family, seniority, IDF-weighted must-have coverage
with evidence tiers, and BM25, combined with fixed weights. ROC-AUC 0.950 on
the benchmark set, about 8 ms per job, no model weights, no network.

This module is the single implementation. ``scripts/matchlab`` imports it, so
the benchmark measures exactly what the queue runs, and the queue preprocessor
uses it to order jobs while CareerOS runs without an LLM (#50). A score orders
the queue; it never removes a job from it.

Everything here is deterministic: regex, table lookups and arithmetic. Same
input, same output.

The role-shape parsing notes below are from the benchmark and still apply.

The central lesson from the failed coverage scorer is here. Representing a job
as a flat bag of skills

    ["Java", "AWS", "React", "CI/CD", "Kubernetes"]

loses the thing that actually decides fit. A frontend posting listing React,
TypeScript, testing and CI/CD scored 100% against this candidate while a backend
posting scored 61.9%, because the frontend posting happened to list fewer, more
generic requirements and the candidate nominally satisfies all of them.

So a job is represented as a *shape* instead:

    role_family        what kind of engineer the posting wants
    seniority          what level
    must_have          requirements with weights
    preferred          requirements with lower weights

A role-family mismatch can then outweigh any amount of generic keyword overlap,
which is the specific failure being fixed.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Role families
# ---------------------------------------------------------------------------
# Cues are ordered by how strongly they imply the family. A title cue is worth
# far more than a body cue: a posting titled "Android Engineer" is an Android
# job whatever its body says about microservices, whereas a body that mentions
# Android once may just be describing a client the team supports.

ROLE_FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "frontend": {
        "title": (r"front.?end", r"\bui\b", r"web developer", r"javascript engineer"),
        "body": (r"react", r"typescript", r"css", r"single.page", r"browser",
                 r"responsive design", r"figma", r"accessibility"),
    },
    "mobile": {
        "title": (r"android", r"\bios\b", r"mobile", r"react native", r"flutter"),
        "body": (r"jetpack compose", r"swiftui", r"app store", r"play store",
                 r"mobile app"),
    },
    "backend": {
        "title": (r"back.?end", r"server.side", r"\bapi engineer"),
        "body": (r"microservice", r"\brest\b", r"grpc", r"database", r"\bapi\b",
                 r"server", r"backend service"),
    },
    "platform": {
        "title": (r"platform", r"developer experience", r"\bdevex\b", r"tooling",
                  r"developer productivity"),
        "body": (r"internal platform", r"developer platform", r"ci/cd",
                 r"build system", r"golden path", r"paved road"),
    },
    "infrastructure": {
        "title": (r"infrastructure", r"\bcloud engineer", r"\bdevops\b", r"systems engineer"),
        "body": (r"terraform", r"kubernetes", r"provisioning", r"iac",
                 r"infrastructure as code", r"cloud infrastructure"),
    },
    "sre": {
        "title": (r"\bsre\b", r"site reliability", r"reliability engineer",
                  r"production engineer"),
        "body": (r"on.call", r"incident", r"slo\b", r"error budget", r"postmortem",
                 r"observability", r"uptime"),
    },
    "data": {
        "title": (r"data engineer", r"analytics engineer", r"data scientist",
                  r"data platform"),
        "body": (r"\betl\b", r"data pipeline", r"warehouse", r"spark", r"airflow",
                 r"\bdbt\b", r"snowflake"),
    },
    "ml": {
        "title": (r"machine learning", r"\bml\b", r"\bai engineer", r"applied scientist",
                  r"\bmlops\b", r"research engineer"),
        "body": (r"model training", r"inference", r"pytorch", r"tensorflow",
                 r"feature store", r"embeddings", r"\bllm\b"),
    },
    "security": {
        "title": (r"security", r"\bappsec\b", r"detection", r"threat", r"trust and safety"),
        "body": (r"threat model", r"vulnerabilit", r"siem", r"detection engineering",
                 r"compliance", r"risk detection", r"insider risk"),
    },
    "fullstack": {
        "title": (r"full.?stack",),
        "body": (r"end.to.end ownership", r"front.?end and back.?end"),
    },
}

#: Which families are close enough that a mismatch between them is mild. Used so
#: an infrastructure candidate is not treated as equally wrong for a platform
#: role as for an Android role.
FAMILY_AFFINITY: dict[tuple[str, str], float] = {
    ("backend", "platform"): 0.75,
    ("backend", "infrastructure"): 0.70,
    ("backend", "sre"): 0.65,
    ("backend", "security"): 0.60,
    ("backend", "data"): 0.55,
    ("backend", "ml"): 0.50,
    ("backend", "fullstack"): 0.60,
    ("platform", "infrastructure"): 0.90,
    ("platform", "sre"): 0.80,
    ("platform", "security"): 0.55,
    ("platform", "fullstack"): 0.40,
    ("infrastructure", "sre"): 0.85,
    ("infrastructure", "security"): 0.55,
    ("sre", "security"): 0.50,
    ("data", "ml"): 0.70,
    ("data", "platform"): 0.50,
    ("ml", "security"): 0.35,
    ("fullstack", "frontend"): 0.70,
    ("fullstack", "mobile"): 0.35,
    ("frontend", "mobile"): 0.55,
}


def family_affinity(a: str, b: str) -> float:
    """How related two role families are, 0..1. Symmetric, 1.0 for identical."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.5  # unknown shape: neither reward nor punish
    return FAMILY_AFFINITY.get((a, b)) or FAMILY_AFFINITY.get((b, a)) or 0.25


SENIORITY_LEVELS: tuple[tuple[str, int], ...] = (
    (r"\bintern\b|\bnew grad\b|\bgraduate\b", 0),
    (r"\bjunior\b|\bassociate\b|\bentry.level\b|\bi{1,2}\b(?!\w)", 1),
    (r"\bsenior\b|\bsr\.?\b|\bsenior[- ]level\b|\biii\b", 3),
    (r"\bstaff\b|\bprincipal\b|\blead\b|\barchitect\b|\bdistinguished\b", 4),
    (r"\bmanager\b|\bdirector\b|\bhead of\b|\bvp\b", 5),
)
DEFAULT_SENIORITY = 2  # plain "Software Engineer"


def detect_seniority(title: str) -> int:
    for pattern, level in SENIORITY_LEVELS:
        if re.search(pattern, title, re.I):
            return level
    return DEFAULT_SENIORITY


def detect_role_family(title: str, body: str) -> tuple[str, dict[str, float]]:
    """Best-guess role family plus the full score vector.

    Title cues are weighted an order of magnitude above body cues, and body
    cues saturate, so a long posting cannot win on repetition alone.
    """
    title_l, body_l = title.lower(), body.lower()
    scores: dict[str, float] = {}
    for family, cues in ROLE_FAMILIES.items():
        title_hits = sum(1 for c in cues["title"] if re.search(c, title_l))
        body_hits = sum(1 for c in cues["body"] if re.search(c, body_l))
        # Saturating body contribution: 0 -> 0, 1 -> .35, 3 -> .69, 8 -> .89
        body_signal = 1.0 - (0.72 ** body_hits) if body_hits else 0.0
        scores[family] = title_hits * 3.0 + body_signal
    best = max(scores, key=lambda k: scores[k])
    return (best if scores[best] > 0.5 else ""), scores


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------

_MUST_MARKERS = re.compile(
    r"(required|must have|minimum qualifications|basic qualifications|you have|"
    r"what you.ll need|requirements|qualifications)", re.I
)
_NICE_MARKERS = re.compile(
    r"(preferred|nice to have|bonus|plus|desired|good to have|ideally)", re.I
)
_RESP_MARKERS = re.compile(
    r"(responsibilities|what you.ll do|the role|about the role|day to day|"
    r"you will|in this role)", re.I
)

_BULLET = re.compile(r"^\s*(?:[-*•●▪–]|\d+[.)])\s+(.{12,400})$", re.M)


def _segment(description: str) -> dict[str, str]:
    """Split a posting into must / preferred / responsibilities / rest.

    Deliberately crude. Postings are not consistently structured, and a parser
    that tries to be clever about them is a parser that fails silently on the
    next board. Anything unrecognised stays in "rest" and is still scored.
    """
    lines = description.splitlines()
    buckets = {"must": [], "preferred": [], "responsibilities": [], "rest": []}
    current = "rest"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # A short line that looks like a heading switches the active bucket.
        if len(stripped) < 80:
            if _NICE_MARKERS.search(stripped):
                current = "preferred"
                continue
            if _MUST_MARKERS.search(stripped):
                current = "must"
                continue
            if _RESP_MARKERS.search(stripped):
                current = "responsibilities"
                continue
        buckets[current].append(stripped)
    return {k: "\n".join(v) for k, v in buckets.items()}


def extract_requirements(text: str) -> list[str]:
    """Requirement-like lines. Falls back to sentences when there are no bullets."""
    bullets = [m.group(1).strip() for m in _BULLET.finditer(text)]
    if bullets:
        return bullets
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 25 < len(s.strip()) < 400]


@dataclass
class JobShape:
    title: str
    company: str
    description: str
    role_family: str = ""
    family_scores: dict[str, float] = field(default_factory=dict)
    seniority: int = DEFAULT_SENIORITY
    must_have: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "company": self.company,
            "roleFamily": self.role_family, "seniority": self.seniority,
            "mustHave": self.must_have[:12], "preferred": self.preferred[:12],
            "responsibilities": self.responsibilities[:12],
        }


def parse_job(title: str, company: str, description: str) -> JobShape:
    sections = _segment(description)
    family, scores = detect_role_family(title, description)
    return JobShape(
        title=title, company=company, description=description,
        role_family=family, family_scores=scores,
        seniority=detect_seniority(title),
        must_have=extract_requirements(sections["must"] or sections["rest"]),
        preferred=extract_requirements(sections["preferred"]),
        responsibilities=extract_requirements(
            sections["responsibilities"] or sections["rest"]
        ),
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Resume side
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """One thing the candidate can point at, and how strongly."""

    text: str
    source: str            # professional | project | skills | education
    company: str = ""
    tier: float = 1.0      # strength multiplier for this kind of evidence

    @property
    def is_professional(self) -> bool:
        return self.source == "professional"


@dataclass
class ResumeShape:
    headline: str
    professional: list[Evidence] = field(default_factory=list)
    projects: list[Evidence] = field(default_factory=list)
    skills: list[Evidence] = field(default_factory=list)
    role_family: str = ""
    seniority: int = 3

    @property
    def all_evidence(self) -> list[Evidence]:
        return self.professional + self.projects + self.skills


#: How much weight each kind of evidence carries. These are *parameters*, swept
#: in the ablation study rather than asserted - the brief is explicit that
#: hard-coding a multiplier and declaring success is not an experiment.
DEFAULT_TIERS = {"professional": 1.0, "project": 0.45, "skills": 0.25, "education": 0.2}


def build_resume_shape(
    corpus: list[dict[str, Any]],
    headline: str = "",
    tiers: dict[str, float] | None = None,
) -> ResumeShape:
    """Turn the story corpus into weighted evidence.

    The corpus already carries the distinction that matters: every story is
    tagged professional or personal-project, and that tag was set from the
    source material rather than inferred. Kubernetes evidence that exists only
    in a side project must not read as production ownership.
    """
    tiers = tiers or DEFAULT_TIERS
    shape = ResumeShape(headline=headline)
    for story in corpus:
        evidence_kind = "professional" if story.get("evidence") == "professional" else "project"
        text = " ".join(filter(None, [
            story.get("title", ""), story.get("headline", ""),
            " ".join(story.get("technologies") or []),
            " ".join(story.get("concepts") or []),
        ]))
        item = Evidence(
            text=text, source=evidence_kind,
            company=story.get("company", ""), tier=tiers[evidence_kind],
        )
        (shape.professional if evidence_kind == "professional" else shape.projects).append(item)
    return shape


# ---------------------------------------------------------------------------
# Tokens and corpus statistics
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9+#.]{2,}")

_STOP = frozenset("""
the and for with that this from will have are was been being our your you all can
may must should would about into through during before after above below between
each other some such than too very just also who whom what which when where why how
a an of in on at to by as is it be or if we us they them their there here not no
role team work working experience years year strong ability able help make made
join company opportunity benefits equal employer position candidate candidates
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(str(text or "").lower()) if t not in _STOP and len(t) > 2]


@dataclass
class Corpus:
    """Document frequencies fitted over the whole job corpus.

    Fitting IDF across the corpus rather than one posting is the point: it is
    what makes "Kubernetes" count for more than "engineering", automatically,
    without anyone maintaining a list of important words.
    """

    document_count: int
    document_frequency: Counter
    average_length: float

    def idf(self, term: str) -> float:
        # BM25's probabilistic IDF, with the +1 that keeps it non-negative for
        # terms appearing in more than half the corpus.
        df = self.document_frequency.get(term, 0)
        return math.log(1 + (self.document_count - df + 0.5) / (df + 0.5))

    def tfidf_idf(self, term: str) -> float:
        df = self.document_frequency.get(term, 0)
        return math.log((self.document_count + 1) / (df + 1)) + 1.0


def fit_corpus(documents: list[str]) -> Corpus:
    df = Counter()
    lengths = []
    for document in documents:
        tokens = tokenize(document)
        lengths.append(len(tokens))
        df.update(set(tokens))
    return Corpus(
        document_count=len(documents),
        document_frequency=df,
        average_length=(sum(lengths) / len(lengths)) if lengths else 1.0,
    )


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def bm25(query_tokens: list[str], doc_tokens: list[str], corpus: Corpus,
         k1: float = 1.5, b: float = 0.75) -> float:
    """Standard Okapi BM25. The query is the posting, the document is the resume."""
    if not doc_tokens:
        return 0.0
    counts = Counter(doc_tokens)
    length = len(doc_tokens)
    score = 0.0
    # Sorted, not set order: string hashing is randomised per process, and a
    # float sum taken in a different order can differ in its last bits. Sorting
    # makes the score identical across API restarts, not just within one run.
    for term in sorted(set(query_tokens)):
        tf = counts.get(term, 0)
        if not tf:
            continue
        denominator = tf + k1 * (1 - b + b * length / (corpus.average_length or 1))
        score += corpus.idf(term) * (tf * (k1 + 1)) / denominator
    return score


# ---------------------------------------------------------------------------
# Scoring context and the role-shape score
# ---------------------------------------------------------------------------

class JobText(Protocol):
    """What a scorer reads from a posting: the benchmark's Pair satisfies it."""

    title: str
    company: str
    description: str


@dataclass
class Context:
    """Everything a scorer may use, built once for the whole run."""

    corpus: Corpus
    resume: ResumeShape
    resume_text: str
    resume_tokens: list[str]
    professional_text: str
    project_text: str
    skills_text: str
    resume_family: str = "backend"
    resume_seniority: int = 3
    tiers: dict[str, float] = None  # type: ignore[assignment]
    #: Scratch space for anything expensive that is constant across pairs -
    #: resume embeddings above all. Computing those once rather than per job is
    #: the difference between a usable bi-encoder and a pointless one.
    cache: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tiers is None:
            self.tiers = dict(DEFAULT_TIERS)
        if self.cache is None:
            self.cache = {}


def _scale(raw: float, ceiling: float) -> float:
    """Map an unbounded similarity onto 0..100 without clipping information away."""
    return 100.0 * (raw / (raw + ceiling)) if raw > 0 else 0.0


def role_shape_components(pair: JobText, ctx: Context) -> dict[str, float]:
    """The individual signals, exposed so ablations can turn them off."""
    return _components(parse_job(pair.title, pair.company, pair.description), ctx)


def _components(job: JobShape, ctx: Context) -> dict[str, float]:
    """``role_shape_components`` for a posting that is already parsed."""
    affinity = family_affinity(job.role_family, ctx.resume_family)

    # Seniority: being one level under is a real mismatch, being over is mild.
    gap = job.seniority - ctx.resume_seniority
    seniority = 1.0 if gap == 0 else (0.85 if gap < 0 else max(0.0, 1.0 - 0.35 * gap))

    must_tokens = tokenize(" ".join(job.must_have)) or tokenize(job.description)
    professional = tokenize(ctx.professional_text)
    project = tokenize(ctx.project_text)

    # Evidence is weighted by where it comes from, and rare requirements count
    # for more than common ones - that is what stops a long list of generic
    # requirements outweighing a few decisive ones.
    pro_set, proj_set = set(professional), set(project)
    weighted_hit = 0.0
    weighted_total = 0.0
    for term in sorted(set(must_tokens)):  # sorted for cross-process determinism, as in bm25
        weight = ctx.corpus.idf(term)
        weighted_total += weight
        if term in pro_set:
            weighted_hit += weight * ctx.tiers["professional"]
        elif term in proj_set:
            weighted_hit += weight * ctx.tiers["project"]
    coverage = (weighted_hit / weighted_total) if weighted_total else 0.0

    return {
        "family": affinity,
        "seniority": seniority,
        "coverage": coverage,
        "bm25": _scale(bm25(must_tokens, ctx.resume_tokens, ctx.corpus), 30.0) / 100.0,
    }


#: Initial experimental weights. Swept in the ablation, not asserted.
ROLE_SHAPE_WEIGHTS = {"family": 0.45, "seniority": 0.10, "coverage": 0.30, "bm25": 0.15}


def score_role_shape(pair: JobText, ctx: Context) -> float:
    parts = role_shape_components(pair, ctx)
    return 100.0 * sum(ROLE_SHAPE_WEIGHTS[k] * v for k, v in parts.items())


# ---------------------------------------------------------------------------
# Building the context: shared by the benchmark and the queue
# ---------------------------------------------------------------------------

def build_context(
    profile: dict[str, Any],
    documents: dict[str, Any],
    corpus_records: list[dict[str, Any]],
    job_descriptions: list[str],
) -> Context:
    """The resume side of every score, plus IDF fitted over the postings.

    ``job_descriptions`` is what IDF is fitted on. The benchmark passes its
    evaluation set; the queue passes every active posting, so a job's score does
    not depend on which other jobs happened to arrive in the same batch.
    """
    from app.services.application_assistant.candidate_match_context import extract_resume_text

    resume = build_resume_shape(corpus_records, headline=str(profile.get("headline") or ""))

    professional = " ".join(e.text for e in resume.professional)
    project = " ".join(e.text for e in resume.projects)
    resume_text = extract_resume_text(documents) or ""
    skills = " ".join(
        str(s) for s in (profile.get("skills") or [])
    ) if isinstance(profile.get("skills"), list) else str(profile.get("skills") or "")

    combined = f"{resume_text}\n{professional}\n{project}\n{skills}"

    # IDF is fitted over the postings, which is what makes common hiring
    # vocabulary cheap and specific technology expensive.
    corpus = fit_corpus(list(job_descriptions) + [combined])

    family, _ = detect_role_family(
        str(profile.get("headline") or "Senior Software Engineer"), combined
    )
    return Context(
        corpus=corpus, resume=resume, resume_text=combined,
        resume_tokens=tokenize(combined),
        professional_text=professional + "\n" + resume_text,
        project_text=project, skills_text=skills,
        resume_family=family or "backend", resume_seniority=3,
    )


# ---------------------------------------------------------------------------
# Queue scoring
# ---------------------------------------------------------------------------

MATCH_METHOD = "role-shape"

#: Matches carrying one of these methods came from a model and are left alone:
#: the model path is out of scope for deterministic scoring (#50).
MODEL_MATCH_METHODS = frozenset({"ollama-local", "mistral-ollama", "qwen"})


def _reason(job: JobShape, parts: dict[str, float], ctx: Context, has_text: bool) -> str:
    family = job.role_family or "unclear"
    pieces = [
        f"Role family {family} vs your {ctx.resume_family} "
        f"({parts['family'] * 100:.0f}% affinity)",
        f"seniority fit {parts['seniority'] * 100:.0f}%",
    ]
    if has_text:
        pieces.append(f"requirement coverage {parts['coverage'] * 100:.0f}%")
    else:
        pieces.append("no posting text, so scored on the title alone")
    return "Role-shape match: " + "; ".join(pieces) + "."


def match_for(job: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """A match record in the shape the queue already stores for model scores."""
    shape = parse_job(
        str(job.get("title") or ""),
        str(job.get("company") or ""),
        str(job.get("description") or ""),
    )
    parts = _components(shape, ctx)
    has_text = bool(tokenize(shape.description))
    if has_text:
        score = 100.0 * sum(ROLE_SHAPE_WEIGHTS[k] * v for k, v in parts.items())
    else:
        # With no text, coverage and BM25 are 0 for want of data, not for want
        # of fit. Scoring them as 0 would rank every text-less posting below
        # every described one. Renormalise over the two signals that exist
        # (the ablation measured family + seniority alone at 0.945 ROC-AUC).
        used = ("family", "seniority")
        score = 100.0 * sum(ROLE_SHAPE_WEIGHTS[k] * parts[k] for k in used) / sum(
            ROLE_SHAPE_WEIGHTS[k] for k in used
        )
    return {
        "matchScore": round(score, 1),
        "matchReason": _reason(shape, parts, ctx, has_text),
        # Role shape does not produce a skill list, and bare tokens would be
        # passed off as one, so these stay empty rather than invented.
        "keyMatchingSkills": [],
        "missingSkills": [],
        "matchMethod": MATCH_METHOD,
        "matchModel": "",
        "roleFamily": shape.role_family,
        "matchComponents": {k: round(v, 4) for k, v in parts.items()},
    }


def score_jobs(jobs: list[dict[str, Any]], ctx: Context) -> dict[str, dict[str, Any]]:
    """Role-shape matches for ``jobs``, keyed by job id. Pure: no I/O."""
    return {str(job.get("id")): match_for(job, ctx) for job in jobs if job.get("id")}


# ---------------------------------------------------------------------------
# The queue's scorer: cached context, memoised matches, bounded work per call
# ---------------------------------------------------------------------------

#: Most new postings scored in one call. The queue sees every active posting
#: that is not yet queued, which is thousands; at a few ms each an unbounded
#: pass is tens of seconds of CPU on the API process. Postings past the budget
#: stay unscored for this call and are scored on the next one.
MAX_NEW_SCORES_PER_CALL = 500

#: Refit IDF when the number of active postings drifts by more than this.
IDF_REFIT_DRIFT = 0.10


def _fingerprint(*parts: Any) -> str:
    import hashlib
    import json

    payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


class QueueScorer:
    """Role-shape scores for the queue, computed once per posting.

    The context (resume shape plus IDF over every active posting) is rebuilt
    only when the resume side changes or the posting pool drifts, and every
    rebuild clears the memo, so all scores in the memo come from one context.
    Thread-safe: the preprocessor and the runner's refill both call it from
    worker threads.
    """

    def __init__(self, max_new_per_call: int = MAX_NEW_SCORES_PER_CALL) -> None:
        import threading

        self._lock = threading.Lock()
        self._max_new = max_new_per_call
        self._ctx: Context | None = None
        self._resume_key = ""
        self._fitted_on = 0
        self._memo: dict[str, tuple[str, dict[str, Any]]] = {}

    def _context(
        self,
        profile: dict[str, Any],
        documents: dict[str, Any],
        idf_documents: list[str],
    ) -> Context:
        from app.services.story_index import load_corpus

        corpus_records = load_corpus()
        resume_key = _fingerprint(profile, documents, corpus_records)
        count = len(idf_documents)
        drifted = abs(count - self._fitted_on) > IDF_REFIT_DRIFT * max(self._fitted_on, 1)
        if self._ctx is None or resume_key != self._resume_key or drifted:
            self._ctx = build_context(profile, documents, corpus_records, idf_documents)
            self._resume_key = resume_key
            self._fitted_on = count
            self._memo.clear()
        return self._ctx

    def matches(
        self,
        jobs: list[dict[str, Any]],
        profile: dict[str, Any],
        documents: dict[str, Any],
        idf_documents: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Matches keyed by job id: every memoised one, plus up to the budget of new ones."""
        with self._lock:
            ctx = self._context(profile, documents, idf_documents)
            out: dict[str, dict[str, Any]] = {}
            scored_now = 0
            for job in jobs:
                job_id = str(job.get("id") or "")
                if not job_id:
                    continue
                text_key = _fingerprint(job.get("title"), job.get("company"), job.get("description"))
                cached = self._memo.get(job_id)
                if cached and cached[0] == text_key:
                    out[job_id] = cached[1]
                    continue
                if scored_now >= self._max_new:
                    continue
                match = match_for(job, ctx)
                self._memo[job_id] = (text_key, match)
                out[job_id] = match
                scored_now += 1
                # Hand the GIL back between postings. Scoring is regex work in
                # C, which the interpreter's switch interval cannot preempt, so
                # without this the API's event loop stalls for 100-250 ms at a
                # time while a batch is scored (measured, #50).
                time.sleep(0)
            return out


queue_scorer = QueueScorer()


def role_shape_matches(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    documents: dict[str, Any],
    discovered: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Role-shape matches for ``jobs``, with IDF fitted over every active posting.

    Never raises: a scoring failure leaves the jobs unscored, which queues them
    exactly as before, rather than stopping the queue from filling.
    """
    if not jobs:
        return {}
    try:
        return queue_scorer.matches(
            jobs, profile, documents,
            [str(j.get("description") or "") for j in discovered],
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Role-shape scoring failed; leaving %d posting(s) unscored", len(jobs)
        )
        return {}
