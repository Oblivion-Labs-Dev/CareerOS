"""Knowledge graph builder from resume corpus records."""

from __future__ import annotations

import math
from typing import Any

from app.services.resume_intelligence.corpus_adapter import accomplishment_to_record

MAX_NODES = 80
MAX_EDGES = 120


def build_knowledge_graph(accomplishments: list[dict[str, Any]]) -> dict[str, Any]:
    records = [accomplishment_to_record(a) for a in accomplishments]
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    width, height = 900, 520
    for index, record in enumerate(records):
        if len(nodes) >= MAX_NODES:
            break
        angle = (index / max(len(records), 1)) * 3.14159 * 2
        radius = 140
        acc_id = f"acc-{record['id']}"
        if acc_id not in seen:
            nodes.append({
                "id": acc_id,
                "label": record["title"],
                "type": "accomplishment",
                "x": width / 2 + math.cos(angle) * radius,
                "y": height / 2 + math.sin(angle) * radius,
                "recordId": record["id"],
            })
            seen.add(acc_id)

        company = record.get("company") or "Unknown company"
        company_id = f"company-{company.lower().replace(' ', '-')}"
        if company_id not in seen and len(nodes) < MAX_NODES:
            nodes.append({
                "id": company_id,
                "label": company,
                "type": "company",
                "x": width / 2 + math.cos(angle) * (radius + 90),
                "y": height / 2 + math.sin(angle) * (radius + 90),
            })
            seen.add(company_id)
        _link(links, acc_id, company_id, "at")

        for tech in record.get("technologies", [])[:4]:
            tech_id = f"skill-{tech.lower()}"
            if tech_id not in seen and len(nodes) < MAX_NODES:
                nodes.append({
                    "id": tech_id,
                    "label": tech,
                    "type": "skill",
                    "x": width / 2 + math.cos(angle + 0.2) * (radius - 70),
                    "y": height / 2 + math.sin(angle + 0.2) * (radius - 70),
                })
                seen.add(tech_id)
            _link(links, acc_id, tech_id, "uses")

        for metric in record.get("metrics", [])[:2]:
            metric_id = f"metric-{metric.get('id') or metric.get('name', '')}"
            if not metric_id or metric_id in seen or len(nodes) >= MAX_NODES:
                continue
            nodes.append({
                "id": metric_id,
                "label": f"{metric.get('name', '')}: {metric.get('value', '')}".strip(": "),
                "type": "metric",
                "x": width / 2 + math.cos(angle + 0.4) * (radius + 40),
                "y": height / 2 + math.sin(angle + 0.4) * (radius + 40),
                "recordId": record["id"],
            })
            seen.add(metric_id)
            _link(links, acc_id, metric_id, "measured")

        for domain in record.get("domains", [])[:2]:
            domain_id = f"domain-{domain.lower()}"
            if domain_id not in seen and len(nodes) < MAX_NODES:
                nodes.append({
                    "id": domain_id,
                    "label": domain,
                    "type": "architecture",
                    "x": width / 2 + math.cos(angle + 0.55) * (radius + 55),
                    "y": height / 2 + math.sin(angle + 0.55) * (radius + 55),
                })
                seen.add(domain_id)
            _link(links, acc_id, domain_id, "in domain")

        if len(links) >= MAX_EDGES:
            break

    return {
        "nodes": nodes[:MAX_NODES],
        "links": links[:MAX_EDGES],
        "stats": {
            "accomplishmentCount": len(records),
            "nodeCount": len(nodes),
            "edgeCount": len(links),
        },
    }


def _link(links: list[dict[str, Any]], source: str, target: str, label: str) -> None:
    if len(links) >= MAX_EDGES:
        return
    links.append({"source": source, "target": target, "label": label})
