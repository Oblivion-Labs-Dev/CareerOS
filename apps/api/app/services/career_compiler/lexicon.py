"""Named technologies, titles and scale words the validator must recognise even when career.json never mentions them.

This is general industry vocabulary, not career facts: a term listed here is only ever used to *reject* a claim
that the cited evidence does not support.
"""
from __future__ import annotations

import re
from functools import lru_cache

TECHNOLOGIES = (
    # Languages and runtimes
    "Go", "Golang", "Rust", "Scala", "Ruby", "PHP", "Swift", "Elixir", "Erlang", "Haskell", "Clojure", "Perl", "Lua",
    "Java", "Kotlin", "Python", "C#", "C++", "TypeScript", "JavaScript", "Node.js", "Deno", ".NET", ".NET Core", "ASP.NET",
    "Objective-C", "Dart", "Julia", "MATLAB", "Bash", "PowerShell", "Solidity", "WebAssembly",
    # Messaging and streaming
    "Kafka", "Apache Kafka", "Confluent", "RabbitMQ", "Pulsar", "ActiveMQ", "NATS", "ZeroMQ", "Kinesis", "SNS", "SQS",
    "EventBridge", "Event Hubs", "Service Bus", "Pub/Sub", "Google Pub/Sub", "Flink", "Apache Flink", "Spark",
    "Apache Spark", "Storm", "Beam", "Hadoop", "Airflow", "Dagster", "Prefect", "Temporal",
    # Data stores
    "PostgreSQL", "Postgres", "MySQL", "MariaDB", "Oracle Database", "SQL Server", "SQLite", "MongoDB", "Cassandra",
    "ScyllaDB", "DynamoDB", "Cosmos DB", "Redis", "Memcached", "Elasticsearch", "OpenSearch", "Solr", "Neo4j",
    "ClickHouse", "Snowflake", "BigQuery", "Redshift", "Databricks", "Presto", "Trino", "Hive", "HBase", "Bigtable",
    "Spanner", "CockroachDB", "TiDB", "Vitess", "etcd", "ZooKeeper", "InfluxDB", "TimescaleDB", "Pinecone", "Weaviate",
    "Milvus", "Qdrant", "Chroma", "pgvector", "FAISS",
    # Cloud and infrastructure
    "AWS", "Azure", "GCP", "Google Cloud", "Oracle Cloud", "Kubernetes", "EKS", "AKS", "GKE", "OpenShift", "Docker",
    "Podman", "Helm", "Istio", "Linkerd", "Envoy", "Consul", "Nomad", "Vault", "Terraform", "Pulumi", "Ansible", "Chef",
    "Puppet", "CloudFormation", "AWS CDK", "Bicep", "ARM", "Lambda", "Fargate", "ECS", "ECR", "EC2", "S3", "Step Functions",
    "API Gateway", "CloudWatch", "App Mesh", "FireLens", "Azure Functions", "Durable Functions", "Azure DevOps",
    "Cloud Run", "Cloud Functions", "Nginx", "HAProxy", "Cloudflare",
    # Observability and CI/CD
    "Prometheus", "Grafana", "Datadog", "Splunk", "New Relic", "Honeycomb", "Jaeger", "Zipkin", "OpenTelemetry",
    "Kusto", "PagerDuty", "Jenkins", "GitHub Actions", "GitLab CI", "CircleCI", "Argo CD", "ArgoCD", "Spinnaker",
    "Bazel", "Gradle", "Maven",
    # APIs and frameworks
    "gRPC", "GraphQL", "REST", "Thrift", "Protobuf", "Avro", "OpenAPI", "React", "Angular", "Vue", "Next.js", "Svelte",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", "Rails", "Guice", "Coral",
    # AI and ML
    "PyTorch", "TensorFlow", "JAX", "Keras", "scikit-learn", "XGBoost", "LightGBM", "Ray", "Triton", "CUDA", "vLLM",
    "TensorRT", "ONNX", "Hugging Face", "OpenAI", "Anthropic", "LangChain", "LangGraph", "LangSmith", "LlamaIndex",
    "Semantic Kernel", "AutoGen", "CrewAI", "MLflow", "Kubeflow", "SageMaker", "Vertex AI", "Bedrock", "Amazon Bedrock",
    "Azure OpenAI", "Azure AI Search", "Copilot Studio", "MCP",
    # Security and identity
    "OAuth 2.0", "OAuth", "OIDC", "SAML", "Okta", "Auth0", "Entra", "Active Directory", "Defender", "Sentinel",
    "Microsoft Purview", "Conditional Access", "OPA", "Snyk", "Wiz", "CrowdStrike",
)

#: Ordinary English words that are also technology names; only the capitalised product spelling counts.
CASE_SENSITIVE = {"Go", "Rust", "Swift", "Spark", "Storm", "Beam", "Hive", "Ray", "Vault", "Consul", "Nomad", "Helm",
                  "Spring", "React", "Angular", "Vue", "Chef", "Puppet", "Chroma", "Triton", "Coral", "Dart", "Rails",
                  "Julia", "Wiz", "Temporal", "Prefect", "REST", "ARM", "S3", "Express", "Flask"}

#: Titles above what career.json records are seniority inflation unless a cited claim or role says them.
TITLES = ("Staff", "Senior Staff", "Principal", "Distinguished", "Fellow", "Director", "Head of", "VP", "Vice President",
          "Chief", "CTO", "Architect", "Engineering Manager", "Tech Lead", "Technical Lead", "Team Lead", "Lead Engineer")

#: Scale words that assert size without a number; each needs the cited evidence to say the same.
SCALE_WORDS = (r"\bmillions?\b", r"\bbillions?\b", r"\btrillions?\b", r"\bpetabytes?\b", r"\bterabytes?\b",
               r"\bplanet[- ]scale\b", r"\binternet[- ]scale\b", r"\bglobal(ly)?\b", r"\bworldwide\b", r"\bhyperscale\b")


@lru_cache(maxsize=None)
def _pattern(term: str) -> re.Pattern[str]:
    if term in CASE_SENSITIVE:
        # "Go-live" and "Spring-loaded" are words, not products.
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9-])")
    exact = term.isupper() and len(term) <= 4
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", 0 if exact else re.I)


def mentions_tech(text: str, term: str) -> bool:
    return len(term) > 1 and bool(_pattern(term).search(text))


@lru_cache(maxsize=8)
def technologies(extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Lexicon plus career.json's own terms, longest first so "AWS CDK" is seen before "AWS"."""
    terms = {t for t in (*TECHNOLOGIES, *extra) if t}
    return tuple(sorted(terms, key=lambda t: (-len(t), t.casefold())))


def named_technology(term: str) -> bool:
    return term.casefold() in {t.casefold() for t in TECHNOLOGIES}
