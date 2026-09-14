"""Technology-to-story index: retrieve only the evidence a job description needs.

The tailoring prompt used to carry a fixed block of every master resume bullet
regardless of what the role asked for. That is wasteful in two directions. The
local model runs on an 8GB card, so every irrelevant character of context is
context the relevant material does not get; and a model asked to match a
Kubernetes platform role against seventeen bullets, fifteen of which are about
fulfillment promises, spends its attention on the fifteen.

This module inverts the problem. Each story in the corpus is tagged with the
technologies, concepts and behavioural themes it genuinely demonstrates. A job
description is tagged with the same vocabulary, and only the stories that
actually overlap are sent to the model.

Three deliberate choices:

* **A controlled vocabulary, not free-text keywords.** ``extract_keywords`` in
  candidate_match_context splits on whitespace and keeps anything over two
  characters, which makes "the", "using" and "team" look like signal. Retrieval
  needs precision more than recall: a wrong story is worse than a missing one,
  because the model will write bullets from whatever it is given.

* **Aliases are normalised on both sides.** A posting says "K8s", "EKS" or
  "container orchestration"; the corpus says "Kubernetes". Matching raw strings
  would miss every one of those. Every surface form maps to one canonical tag
  and both sides are normalised through the same table.

* **Rare tags count for more.** Nearly every story mentions AWS, so "AWS" in a
  posting separates nothing. "quantile regression" appears in exactly one story
  and is close to a perfect selector. Weighting by inverse document frequency
  falls out of that directly, and it is why a posting full of generic cloud
  vocabulary still ranks the right story first.

Nothing here invents evidence. The index can only surface stories that were
already written down; a tag exists because the story text contains the thing.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Controlled vocabulary
# ---------------------------------------------------------------------------
# canonical tag -> surface forms that mean it. The canonical tag is what the
# corpus and the index speak; the surface forms are what job descriptions
# actually write. Keep surface forms lowercase.

TECHNOLOGY_VOCABULARY: dict[str, tuple[str, ...]] = {
    # Languages
    "Python": ("python",),
    "Java": ("java", "jvm"),
    "C#": ("c#", "csharp", "c sharp"),
    ".NET": (".net", "dotnet", "asp.net"),
    "Kotlin": ("kotlin",),
    "Go": ("golang", "go lang"),
    "TypeScript": ("typescript",),
    "JavaScript": ("javascript", "node.js", "nodejs"),
    "SQL": ("sql", "t-sql"),
    "Scala": ("scala",),
    "C/C++": ("c++", "cpp", "c/c++", "systems programming"),
    "Linux Kernel": ("linux kernel", "kernel development", "kernel module", "f2fs", "filesystem performance"),
    "Vue.js": ("vue.js", "vuejs", "vue"),
    # Cloud platforms
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure", "microsoft azure"),
    "GCP": ("gcp", "google cloud"),
    "Azure Government": (
        "azure government", "gcc high", "gcch", "sovereign cloud",
        "govcloud", "gov cloud", "fedramp", "il5", "dod cloud",
    ),
    # Compute / orchestration
    "Kubernetes": ("kubernetes", "k8s", "eks", "aks", "gke", "container orchestration"),
    "Docker": ("docker", "containerization", "containerisation", "container image", "oci image"),
    "Helm": ("helm chart", "helm charts"),
    "ECS": ("ecs", "fargate"),
    "AWS Lambda": ("lambda", "aws lambda", "serverless function"),
    "Azure Durable Functions": (
        "durable function", "durable functions", "azure functions", "durable orchestration",
    ),
    "AWS Step Functions": ("step function", "step functions", "state machine", "workflow orchestration"),
    # Messaging / streaming
    "Kafka": ("kafka", "msk", "event streaming"),
    "Event Hub": ("event hub", "event hubs", "eventhub"),
    "SQS": ("sqs", "simple queue service", "message queue"),
    "SNS": ("sns", "simple notification service", "pub/sub", "pubsub"),
    "Flink": ("flink", "stream processing"),
    "Spark": ("pyspark", "databricks", "apache spark"),
    "Change Data Capture": ("change data capture", "cdc", "debezium"),
    # Storage
    "Cosmos DB": ("cosmos db", "cosmosdb", "cosmos"),
    "DynamoDB": ("dynamodb", "dynamo"),
    "PostgreSQL": ("postgresql", "postgres", "rds"),
    "Redis": ("redis", "elasticache", "in-memory cache"),
    "S3": ("s3", "object storage", "blob storage"),
    "SQLite": ("sqlite",),
    "Neo4j": ("neo4j", "graph database"),
    "OpenSearch": ("opensearch", "elasticsearch"),
    "Kinesis": ("kinesis",),
    "Firebase": ("firebase",),
    # ML / AI
    "SageMaker": ("sagemaker", "sage maker"),
    "XGBoost": ("xgboost", "gradient boosting", "gradient boosted"),
    "Quantile Regression": ("quantile regression", "quantile model", "prediction interval"),
    "LLM": ("llm", "large language model", "generative ai", "genai", "foundation model"),
    "RAG": (
        "rag", "retrieval augmented generation", "retrieval-augmented",
        "vector search", "semantic search", "embeddings",
    ),
    "Ollama": ("ollama", "local inference", "on-device model"),
    "Amazon Bedrock": ("bedrock", "amazon bedrock"),
    "Deep Learning": ("deep learning", "cnn", "convolutional", "neural network"),
    "Machine Learning": (
        "machine learning", "ml model", "ml pipeline", "mlops",
        "inference endpoint", "model serving",
    ),
    # Infra as code / CI
    "AWS CDK": ("cdk", "aws cdk", "cloud development kit"),
    "Terraform": ("terraform", "opentofu"),
    "Bicep": ("bicep",),
    "ARM Templates": ("arm template", "arm templates", "resource manager template"),
    "CI/CD": (
        "ci/cd", "cicd", "continuous integration", "continuous delivery",
        "continuous deployment", "build pipeline", "deployment pipeline",
    ),
    # Observability
    "CloudWatch": ("cloudwatch", "cloud watch"),
    "Kusto": ("kusto", "kql", "azure data explorer"),
    "Prometheus": ("prometheus", "grafana"),
    "OpenTelemetry": ("opentelemetry", "otel", "distributed tracing"),
    # Web / protocol
    "gRPC": ("grpc", "protobuf", "protocol buffers"),
    "REST": ("rest api", "restful", "rest service", "http api"),
    "GraphQL": ("graphql",),
    "React": ("react.js", "next.js", "nextjs"),
    "FastAPI": ("fastapi",),
    "App Mesh": ("app mesh", "envoy", "service mesh", "istio", "sidecar proxy"),
    "Playwright": (
        "playwright", "selenium", "browser automation", "e2e test", "end-to-end test",
    ),
    # Security / identity
    "Microsoft Purview": ("purview", "insider risk", "insider risk management"),
    "Microsoft Defender": ("defender", "xdr", "edr"),
    "Microsoft Entra": ("entra", "active directory", "azure ad"),
    "Conditional Access": ("conditional access",),
    "DLP": ("dlp", "data loss prevention"),
    "Managed Identity": ("managed identity", "workload identity", "key vault", "secrets manager"),
    "OAuth": ("oauth", "oauth 2.0", "sso", "openid", "passport.js"),
    "RBAC": ("rbac", "role-based access", "access control"),
    "WebSockets": ("websocket", "websockets", "real-time sync"),
    # --- Requested often, evidenced nowhere -------------------------------
    # These have no story behind them, and that is exactly why they are here.
    # A vocabulary that only contains what the candidate has done reports 100%
    # coverage on a posting demanding Rust and Snowflake, because it never saw
    # the words. Naming them makes them show up in `uncovered`, which is the
    # honest answer and the input to deciding what to build next.
    "Rust": ("rust", "rustlang"),
    "Snowflake": ("snowflake",),
    "Airflow": ("airflow", "dagster", "prefect"),
    "dbt": ("dbt",),
    "Swift": ("swift", "ios development"),
    "Android": ("android", "jetpack compose"),
    "React Native": ("react native", "flutter"),
    "Ruby on Rails": ("ruby on rails", "rails", "ruby"),
    "PHP": ("php", "laravel"),
    "Elixir": ("elixir", "erlang"),
    "Ansible": ("ansible", "puppet", "chef"),
    "Argo CD": ("argocd", "argo cd", "gitops"),  # not bare "flux": "the platform is in flux"
    "Datadog": ("datadog", "new relic", "splunk"),
    "Pulsar": ("pulsar", "rabbitmq", "nats"),
    "Cassandra": ("cassandra", "scylladb"),
    "MongoDB": ("mongodb", "mongo"),
    "ClickHouse": ("clickhouse", "druid"),
    "PyTorch": ("pytorch", "tensorflow", "jax"),
    "LangChain": ("langchain", "llamaindex"),
    "Pinecone": ("pinecone", "weaviate", "milvus", "vector database", "qdrant"),
}

CONCEPT_VOCABULARY: dict[str, tuple[str, ...]] = {
    "Distributed Systems": ("distributed system", "distributed systems", "distributed architecture"),
    "Microservices": ("microservice", "microservices", "service oriented", "monolith to microservices"),
    "Event-Driven Architecture": (
        "event driven", "event-driven", "event sourcing", "asynchronous processing", "async processing",
    ),
    "Eventual Consistency": ("eventual consistency", "eventually consistent", "consistency model"),
    "Idempotency": (
        "idempotent", "idempotency", "exactly once", "at-least-once",
        "at least once", "deduplication", "dedupe",
    ),
    "Fault Isolation": (
        "fault isolation", "blast radius", "bulkhead", "noisy neighbour",
        "noisy neighbor", "failure isolation",
    ),
    "Resilience": (
        "resilience", "resiliency", "fault tolerance", "fault tolerant", "retry",
        "exponential backoff", "circuit breaker", "graceful degradation", "failover",
    ),
    "Scalability": (
        "scalability", "scalable", "high throughput", "horizontal scaling",
        "autoscaling", "auto-scaling", "tps", "high scale",
    ),
    "High Availability": (
        "high availability", "multi-az", "multi az", "disaster recovery",
        "rto", "rpo", "uptime", "sla",
    ),
    "Data Migration": ("migration", "cutover", "backfill", "replay", "zero downtime"),
    "API Design": (
        "api design", "api contract", "service contract", "interface design",
        "schema design", "versioning",
    ),
    "System Design": ("system design", "architecture design", "technical design", "design doc", "rfc"),
    "Observability": (
        "observability", "monitoring", "alerting", "telemetry", "dashboards", "logging", "metrics",
    ),
    "Incident Response": (
        "incident", "on-call", "oncall", "sev1", "sev2", "postmortem",
        "post-mortem", "root cause", "correction of error", "outage",
    ),
    "Performance Optimization": (
        "performance optimization", "performance tuning", "latency", "p99",
        "throughput optimization", "profiling", "bottleneck",
    ),
    "Cost Optimization": ("cost optimization", "cost reduction", "cost savings", "efficiency", "finops"),
    "Security": (
        "security", "threat", "risk detection", "compliance", "audit log",
        "governance", "authentication", "authorization",
    ),
    "Testing Strategy": (
        "test strategy", "testing strategy", "integration test", "regression test",
        "load test", "shadow test", "shadow mode", "canary", "a/b test", "ab test",
    ),
    "Developer Productivity": (
        "developer productivity", "developer experience", "devex", "tooling",
        "internal platform", "self-serve", "self serve", "bootstrapping", "boilerplate",
    ),
    "Platform Engineering": (
        "platform engineering", "internal developer platform", "golden path",
        "paved road", "reusable infrastructure",
    ),
    "Data Pipelines": ("data pipeline", "etl", "batch processing", "ingestion pipeline"),
    "Anti-Fabrication Guardrails": (
        "hallucination", "guardrail", "grounding", "model safety", "responsible ai",
    ),
    "Cross-Team Collaboration": (
        "cross-team", "cross team", "cross-functional", "stakeholder",
        "partner team", "influence without authority",
    ),
    "Mentorship": ("mentor", "mentorship", "coaching", "onboarding engineers", "code review culture"),
    "Technical Leadership": (
        "technical leadership", "tech lead", "led a team", "drove alignment",
        "staff engineer", "principal engineer",
    ),
    "Ownership Boundaries": (
        "ownership boundary", "ownership boundaries", "service ownership", "you build it you run it",
    ),
    "Localization": (
        "localization", "localisation", "internationalization", "i18n", "multi-language", "locales",
    ),
}

BEHAVIOURAL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "Adaptability": ("adaptability", "adapt to change", "ambiguity", "changing requirements"),
    "Conflict Resolution": ("disagreement", "conflict", "pushback", "difficult conversation"),
    "Prioritization": ("prioritization", "prioritisation", "competing priorities", "trade-off", "tradeoff"),
    "Ownership": ("ownership", "end-to-end", "end to end", "took initiative", "bias for action"),
    "Failure and Learning": ("failure", "mistake", "missed deadline", "lessons learned"),
    "Growth": ("growth", "career development", "upskilling"),
    "Collaboration": ("collaboration", "teamwork", "pairing", "knowledge sharing"),
    "Customer Focus": ("customer obsession", "customer focus", "customer experience", "user experience"),
}

_ALL_VOCABULARIES: dict[str, dict[str, tuple[str, ...]]] = {
    "technologies": TECHNOLOGY_VOCABULARY,
    "concepts": CONCEPT_VOCABULARY,
    "behavioural": BEHAVIOURAL_VOCABULARY,
}


# Tags whose name is also an ordinary English word. Matching these
# case-insensitively tagged "go through the templates" as the Go language,
# "at the helm" as Helm, and "the rest of the team" as REST - which put a
# behavioural story about team culture at the top of a Go backend search. The
# written form is the only signal that separates them, so for these the
# canonical spelling must match exactly; their unambiguous surface forms
# ("golang", "rest api", "helm chart") stay case-insensitive.
CASE_SENSITIVE_CANONICALS = frozenset({"Go", "REST", "Helm", "Spark", "React", "SQL", "ECS", "SNS", "S3"})


def _surface_pattern(form: str, *, case_sensitive: bool = False) -> re.Pattern[str]:
    r"""A boundary-aware matcher for one surface form.

    ``\b`` is useless for a vocabulary containing "c#", ".net" and "ci/cd" -
    the boundary lands in the wrong place or nowhere at all. Explicit
    alphanumeric lookarounds give the behaviour ``\b`` was wanted for while
    tolerating punctuation inside the term, and whitespace in a multi-word form
    is allowed to be any run of whitespace or hyphens so "event driven",
    "event-driven" and "event  driven" all match one entry.
    """
    escaped = re.escape(form).replace(r"\ ", r"[\s\-]+")
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9])({escaped})(?![A-Za-z0-9])", flags)


@lru_cache(maxsize=1)
def _compiled_vocabulary() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    compiled: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for kind, vocabulary in _ALL_VOCABULARIES.items():
        entries: list[tuple[str, re.Pattern[str]]] = []
        for canonical, forms in vocabulary.items():
            strict = canonical in CASE_SENSITIVE_CANONICALS
            entries.append(
                (canonical, _surface_pattern(canonical if strict else canonical.lower(),
                                             case_sensitive=strict))
            )
            for form in forms:
                entries.append((canonical, _surface_pattern(form)))
        compiled[kind] = entries
    return compiled


def extract_tags(text: str) -> dict[str, set[str]]:
    """Canonical tags present in a block of text, grouped by vocabulary."""
    if not text:
        return {kind: set() for kind in _ALL_VOCABULARIES}
    found: dict[str, set[str]] = {kind: set() for kind in _ALL_VOCABULARIES}
    for kind, entries in _compiled_vocabulary().items():
        for canonical, pattern in entries:
            if canonical in found[kind]:
                continue
            if pattern.search(text):
                found[kind].add(canonical)
    return found


def flat_tags(text: str) -> set[str]:
    return {tag for group in extract_tags(text).values() for tag in group}


@lru_cache(maxsize=1)
def _tag_category_map() -> dict[str, str]:
    """Canonical tag -> its vocabulary group (technologies/concepts/behavioural).

    A named technology is stronger evidence of role fit than a behavioural
    theme; callers scoring "technical specificity" want that distinction
    without re-deriving it from the vocabulary tables themselves.
    """
    return {canonical: kind for kind, vocabulary in _ALL_VOCABULARIES.items() for canonical in vocabulary}


def tag_category(tag: str) -> str | None:
    return _tag_category_map().get(tag)


def normalize_tag(value: str) -> str | None:
    """Map any surface form onto its canonical tag, or None if unknown.

    Used when reading tags written by hand into the corpus, so a story tagged
    "k8s" and a story tagged "Kubernetes" land on one index key.
    """
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    for vocabulary in _ALL_VOCABULARIES.values():
        for canonical, forms in vocabulary.items():
            if candidate == canonical.lower() or candidate in forms:
                return canonical
    return None


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------

# app/services/story_index.py -> app -> apps/api -> apps -> repo root
CORPUS_PATH = Path(
    os.environ.get("CAREEROS_STORY_CORPUS_PATH")
    or Path(__file__).resolve().parents[4] / "data" / "interview-story-corpus.json"
)

# Tags that describe a story's own subject matter count for more than tags it
# merely mentions in passing. The corpus marks the former as "primary".
PRIMARY_TAG_BOOST = 1.6
TITLE_MATCH_BOOST = 1.4

# Normalising by a story's own tag count alone rewards being narrow: a 1,000
# character story tagged with four things that matches one of them scored
# higher than a deep story that matched five, because its divisor was smaller.
# Flooring the divisor removes that artificial advantage.
MIN_BREADTH = 9.0
# Saturating coverage factor. One shared tag is weak evidence of fit however
# heavily it is weighted; four is strong; twelve is not three times stronger
# than four. k sets where the curve bends.
COVERAGE_K = 1.5

# What kind of evidence a story is. This is not a quality judgement - it is the
# claim the story can support. A bullet written from a personal project must not
# read as professional experience, and the only way to prevent that reliably is
# to carry the distinction all the way into the prompt rather than trusting the
# model to infer it from context.
EVIDENCE_TIERS = ("professional", "personal-project", "planned")
TIER_WEIGHT = {"professional": 1.0, "personal-project": 0.85, "planned": 0.4}
TIER_LABEL = {
    "professional": "professional experience",
    "personal-project": "PERSONAL PROJECT - never describe as professional or employer work",
    "planned": "NOT YET BUILT - must not appear on a resume",
}


@dataclass
class Story:
    id: str
    title: str
    company: str
    kind: str
    headline: str
    body: str
    technologies: set[str] = field(default_factory=set)
    concepts: set[str] = field(default_factory=set)
    behavioural: set[str] = field(default_factory=set)
    primary: set[str] = field(default_factory=set)
    metrics: list[str] = field(default_factory=list)
    do_not_claim: list[str] = field(default_factory=list)
    evidence: str = "professional"
    strength: str = "strong"

    @property
    def all_tags(self) -> set[str]:
        return self.technologies | self.concepts | self.behavioural

    @property
    def tier_weight(self) -> float:
        return TIER_WEIGHT.get(self.evidence, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "kind": self.kind,
            "headline": self.headline,
            "evidence": self.evidence,
            "strength": self.strength,
            "technologies": sorted(self.technologies),
            "concepts": sorted(self.concepts),
            "signals": sorted(self.behavioural),
            "primary": sorted(self.primary),
            "metrics": list(self.metrics),
            "doNotClaim": list(self.do_not_claim),
            "chars": len(self.body),
        }


@dataclass
class Match:
    story: Story
    score: float
    matched: list[str]
    #: Requirements this story was chosen to cover - the ones no
    #: higher-ranked story had already covered. ``matched`` stays the full
    #: overlap so the UI can still show everything the story speaks to.
    covers: list[str] = field(default_factory=list)


class StoryIndex:
    """Inverted index from canonical tag to the stories that evidence it."""

    def __init__(self, stories: Iterable[Story]):
        self.stories: list[Story] = list(stories)
        self.by_id = {story.id: story for story in self.stories}
        self.by_tag: dict[str, list[str]] = {}
        for story in self.stories:
            for tag in story.all_tags:
                self.by_tag.setdefault(tag, []).append(story.id)
        total = max(1, len(self.stories))
        # Smoothed IDF. A tag on every story contributes ~0; a tag on one story
        # contributes the most. The +1 inside the log keeps it non-negative so
        # a universal tag can never subtract from a score.
        self.weights = {
            tag: math.log(1 + total / len(ids)) for tag, ids in self.by_tag.items()
        }

    def tag_map(self) -> dict[str, list[str]]:
        """The technology-to-story map itself, for display and debugging."""
        return {tag: sorted(ids) for tag, ids in sorted(self.by_tag.items())}

    def requirement_weights(self, job_text: str, title: str = "") -> dict[str, float]:
        """The requirements a posting states, and how much each one separates.

        A requirement named in the job title is what the role *is*, not merely
        something it touches, so it outweighs the same word buried in a
        responsibilities list.
        """
        title_tags = flat_tags(title)
        wanted = flat_tags(f"{title}\n{job_text}")
        return {
            tag: self.weights.get(tag, 1.0) * (TITLE_MATCH_BOOST if tag in title_tags else 1.0)
            for tag in wanted
        }

    def rank(self, job_text: str, *, title: str = "", limit: int = 6) -> list[Match]:
        """Every story that overlaps the posting, scored independently.

        Useful for "what else could I talk about", and for building the skill
        map. It is deliberately NOT what feeds the tailoring prompt: several
        stories about the same subject all score highly on the same
        requirement, so the top few can cover one requirement four times over
        and leave the rest of the posting unaddressed. Use ``select`` there.
        """
        wanted = self.requirement_weights(job_text, title)
        if not wanted:
            return []
        matches: list[Match] = []
        for story in self.stories:
            overlap = wanted.keys() & story.all_tags
            if not overlap:
                continue
            score = sum(
                wanted[tag] * (PRIMARY_TAG_BOOST if tag in story.primary else 1.0)
                for tag in overlap
            )
            # Normalise by breadth so a story that tags everything does not win
            # by sheer surface area, while still rewarding genuine coverage.
            score *= len(overlap) / (len(overlap) + COVERAGE_K)
            score /= math.sqrt(max(MIN_BREADTH, len(story.all_tags)))
            score *= story.tier_weight
            if score > 0:
                matches.append(
                    Match(story=story, score=round(score, 4), matched=sorted(overlap),
                          covers=sorted(overlap))
                )
        matches.sort(key=lambda m: (-m.score, m.story.id))
        return matches[:limit]

    def select(
        self,
        job_text: str,
        *,
        title: str = "",
        limit: int = 6,
    ) -> list[Match]:
        """The smallest set of stories that covers the most of this posting.

        Greedy maximum coverage, not top-N by score. The difference is not
        cosmetic: ranked independently, a platform posting returned four
        personal Kubernetes projects that between them covered Kubernetes,
        Terraform and Helm and nothing else, spending every slot on one third of
        the requirements. Choosing each story for what it adds over the ones
        already chosen spends those same slots on Kubernetes, then streaming,
        then observability, then the professional scale evidence.

        Evidence tier is a tie-breaker, not a filter. Professional experience
        wins when the marginal gain is comparable, but a personal project is
        still selected when it is the only evidence for a requirement - the
        alternative is silently claiming a skill with nothing behind it.
        """
        wanted = self.requirement_weights(job_text, title)
        if not wanted:
            return []

        uncovered = dict(wanted)
        chosen: list[Match] = []
        remaining = [s for s in self.stories if s.all_tags & wanted.keys()]

        while remaining and uncovered and len(chosen) < limit:
            best: tuple[float, float, Story] | None = None
            for story in remaining:
                new_tags = story.all_tags & uncovered.keys()
                if not new_tags:
                    continue
                gain = sum(
                    uncovered[tag] * (PRIMARY_TAG_BOOST if tag in story.primary else 1.0)
                    for tag in new_tags
                )
                gain *= story.tier_weight
                if best is None or gain > best[0]:
                    best = (gain, gain, story)
            if best is None or best[0] <= 0:
                break
            gain, _, story = best
            newly = sorted(story.all_tags & uncovered.keys())
            chosen.append(
                Match(
                    story=story,
                    score=round(gain, 4),
                    matched=sorted(story.all_tags & wanted.keys()),
                    covers=newly,
                )
            )
            for tag in newly:
                uncovered.pop(tag, None)
            remaining.remove(story)

        return chosen

    def coverage(self, matches: list[Match], job_text: str, title: str = "") -> dict[str, Any]:
        """How much of the posting the selected stories actually evidence.

        The uncovered list is the honest answer to "what does this role ask for
        that I cannot show" - the same question RESUME-GAPS.md exists to answer,
        now computed per posting instead of once overall.
        """
        wanted = self.requirement_weights(job_text, title)
        covered = {tag for m in matches for tag in m.covers}
        total = sum(wanted.values()) or 1.0
        return {
            "requirements": sorted(wanted),
            "covered": sorted(covered),
            "uncovered": sorted(set(wanted) - covered),
            "weightedCoverage": round(sum(wanted[t] for t in covered) / total, 4),
        }

    def skill_map(self, *, secondary: int = 1) -> dict[str, dict[str, Any]]:
        """Skill -> best evidence, then backup evidence.

        This is the map itself, in the form the user asked for: one entry per
        skill naming the strongest story for it and what else could carry it.
        Ordering within a skill is by how central the skill is to the story
        (primary beats incidental), then by evidence tier, then by depth - a
        story that is *about* Kubernetes beats one that mentions it in passing.
        """
        out: dict[str, dict[str, Any]] = {}
        for tag, ids in self.by_tag.items():
            ranked = sorted(
                (self.by_id[i] for i in ids),
                key=lambda s: (
                    0 if tag in s.primary else 1,
                    EVIDENCE_TIERS.index(s.evidence) if s.evidence in EVIDENCE_TIERS else 9,
                    -len(s.body),
                ),
            )
            out[tag] = {
                "best": ranked[0].id,
                "bestTitle": ranked[0].title,
                "evidence": ranked[0].evidence,
                "secondary": [s.id for s in ranked[1 : 1 + secondary]],
                "allStories": [s.id for s in ranked],
                "weight": round(self.weights.get(tag, 0.0), 4),
            }
        return dict(sorted(out.items()))


def _story_from_record(record: dict[str, Any]) -> Story:
    def tags(key: str) -> set[str]:
        raw = record.get(key) or []
        out: set[str] = set()
        for item in raw if isinstance(raw, list) else []:
            canonical = normalize_tag(str(item))
            out.add(canonical or str(item).strip())
        return {t for t in out if t}

    return Story(
        id=str(record.get("id") or "").strip(),
        title=str(record.get("title") or "").strip(),
        company=str(record.get("company") or "").strip(),
        kind=str(record.get("kind") or "story").strip(),
        headline=str(record.get("headline") or "").strip(),
        body=str(record.get("body") or ""),
        technologies=tags("technologies"),
        concepts=tags("concepts"),
        behavioural=tags("behavioural"),
        primary=tags("primary"),
        metrics=[str(m) for m in (record.get("metrics") or []) if str(m).strip()],
        do_not_claim=[str(m) for m in (record.get("doNotClaim") or []) if str(m).strip()],
        # Default to the most restrictive sensible tier rather than the most
        # flattering: an untagged record is not assumed to be professional
        # experience unless it says so.
        evidence=str(record.get("evidence") or "personal-project").strip(),
        strength=str(record.get("strength") or "strong").strip(),
    )


def load_corpus(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or CORPUS_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [r for r in payload if isinstance(r, dict) and str(r.get("id", "")).strip()]


def get_index() -> StoryIndex:
    # The app and composer read the same current evidence. File data is an
    # import source, not a second live database or a permanently cached index.
    from app.db.store import session_scope, list_entities
    with session_scope() as db:
        records = list_entities(db, "accomplishment")
    stories = []
    for record in records:
        current = (record.get("resumeEvolution") or {}).get("current", record.get("currentBullet") or "")
        nested = record.get("interviewStories") or [{"id": record.get("id"), "body": record.get("description") or current}]
        for story in nested:
            if isinstance(story, dict):
                if not str(story.get("body") or "").strip():
                    continue
                stories.append(_story_from_record({**record, **story,
                    "title": story.get("title") or record.get("project") or record.get("title") or record.get("id"),
                    "headline": current,
                    "technologies": record.get("technologies") or record.get("techStack") or [],
                    "evidence": story.get("evidence") or record.get("evidenceTier") or "personal-project"}))
    return StoryIndex(stories)


def reset_index_cache() -> None:
    pass  # Indexes are rebuilt from the current database snapshot.


# ---------------------------------------------------------------------------
# What actually goes into the prompt
# ---------------------------------------------------------------------------

def _clip_at_paragraph(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    window = cleaned[:limit]
    for boundary in ("\n\n", "\n", ". "):
        cut = window.rfind(boundary)
        if cut > limit * 0.6:
            return window[:cut].rstrip()
    return window.rstrip()


def build_evidence_brief(matches: list[Match], *, char_budget: int = 9000) -> str:
    """The retrieved evidence, formatted for a bullet-writing prompt.

    Each story gets a share of the budget rather than the first story taking
    all of it, because the point of retrieving several is that the model can
    draw on several. Bodies are cut at a paragraph boundary where possible so
    the model never reads half a sentence and completes it itself.
    """
    if not matches:
        return ""
    per_story = max(600, char_budget // max(1, len(matches)))
    blocks: list[str] = []
    for rank, match in enumerate(matches, start=1):
        story = match.story
        header = f"### EVIDENCE {rank}: {story.title}"
        if story.company:
            header += f" ({story.company})"
        parts = [header]
        parts.append(f"Evidence type: {TIER_LABEL.get(story.evidence, story.evidence)}")
        if story.headline:
            parts.append(story.headline)
        parts.append(
            f"Chosen to cover: {', '.join(match.covers or match.matched)}"
            + (
                f" (also demonstrates: {', '.join(t for t in match.matched if t not in match.covers)})"
                if [t for t in match.matched if t not in match.covers]
                else ""
            )
        )
        if story.metrics:
            parts.append(
                "Verified numbers (reuse exactly, never round or inflate): "
                + "; ".join(story.metrics)
            )
        if story.strength == "unwritten":
            # Covered, but with nothing written behind it. Saying so is the
            # point: the model must not turn a confirmed-but-undocumented skill
            # into a bullet, because the only way to do that is to make it up.
            parts.append(
                "NO WRITTEN ACCOUNT YET. The candidate confirms this experience is real, but "
                "no details exist. Do NOT write a bullet from this and do NOT invent detail "
                "for it."
            )
        else:
            parts.append(_clip_at_paragraph(story.body, per_story))
        if story.do_not_claim:
            parts.append("MUST NOT claim from this story: " + "; ".join(story.do_not_claim))
        blocks.append("\n".join(p for p in parts if p.strip()))
    return "\n\n".join(blocks)


def select_evidence_for_job(
    description: str,
    *,
    title: str = "",
    limit: int = 6,
    char_budget: int = 9000,
) -> tuple[str, dict[str, Any]]:
    """Convenience entry point: retrieved brief plus what was selected and why."""
    index = get_index()
    matches = index.select(description, title=title, limit=limit)
    brief = build_evidence_brief(matches, char_budget=char_budget)
    coverage = index.coverage(matches, description, title)
    provenance = [
        {
            "id": m.story.id,
            "title": m.story.title,
            "evidence": m.story.evidence,
            "score": m.score,
            "covers": m.covers,
            "matched": m.matched,
        }
        for m in matches
    ]
    return brief, {"stories": provenance, "coverage": coverage}
