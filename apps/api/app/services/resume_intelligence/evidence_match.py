"""Local document-support diagnostics. Retrieval is not proof or hiring probability.

The cache includes exact document content, normalized JD and scorer settings.
All quotations come from the scored text; corpus/profile facts cannot leak into
a PDF-only comparison. Semantic similarity only chooses candidate quotations.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
from html import unescape
import re

from app.services.resume_intelligence import semantic
from app.services.resume_intelligence.bm25 import BM25Index
from app.services.resume_intelligence.fusion import reciprocal_rank_fusion

VERSION = "document-support-v1"
SKILLS = {
    "Python": ("python",), "Java": ("java",), "JavaScript": ("javascript",),
    "TypeScript": ("typescript",), "C#": ("c#", "c sharp"), "C++": ("c++",),
    "Go": ("go", "golang"), "Rust": ("rust",), "Kotlin": ("kotlin",), "Swift": ("swift",),
    "React": ("react", "react.js", "reactjs"), "Angular": ("angular",), "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"), "MySQL": ("mysql",), "Redis": ("redis",),
    "Kafka": ("kafka",), "Kubernetes": ("kubernetes", "k8s"), "Docker": ("docker",),
    "AWS": ("aws", "amazon web services"), "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"), "Terraform": ("terraform",), "Linux": ("linux",),
    "GraphQL": ("graphql",), "REST": ("rest", "restful"), "gRPC": ("grpc",),
    "Spark": ("spark",), "PyTorch": ("pytorch",), "TensorFlow": ("tensorflow",),
    "SageMaker": ("sagemaker",), "Android": ("android",), "iOS": ("ios",),
    "CI/CD": ("ci/cd", "continuous integration", "continuous delivery"),
    ".NET": (".net", "dotnet"), "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
}
STOP = set("a an the and or to of in on at for with as by from using used use have has had be been is are was were you your our we will must should can required preferred requirement requirements qualification qualifications experience experienced years year knowledge strong proficiency familiar familiarity understanding ability work working building build develop developing development engineer engineering excellent good related demonstrated proven hands hands-on plus including include minimum bonus nice possess highly seeking looking candidate candidates".split())
NEGATIVE = re.compile(r"\b(?:no|without|lack(?:ing|s)?)\s+(?:[\w+#.-]+\s+){0,4}(?:experience|knowledge|expertise|proficiency)\b|\b(?:never|not)\s+(?:used|worked|built|implemented|managed)|\b(?:do|does|did)\s+not\s+(?:know|use|have)|\b(?:unfamiliar|inexperienced)\s+with", re.I)
CLOSER = re.compile(r"^(?:about us|about the company|who we are|our (?:mission|values)|benefits?|compensation|salary|equal opportunity|diversity|inclusion|pay transparency|what we offer|perks|privacy|how to apply|apply now|accommodation|recruitment process)\b", re.I)


def clean(text: str) -> str:
    text = re.sub(r"</?(?:p|li|ul|ol|h[1-6]|div|br)\b[^>]*>", "\n", str(text or ""), flags=re.I)
    return unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")


def contains(text: str, term: str) -> bool:
    if term.lower() == "go":
        text = re.sub(r"\bgo[- ]to[- ]market\b", "", text, flags=re.I)
    return re.search(r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])", text, re.I) is not None


@lru_cache(maxsize=2048)
def terms(text: str) -> frozenset[str]:
    tokens = re.findall(r"\.net|[a-z][a-z0-9]*(?:\+\+|#)?", text.lower())
    return frozenset(t[:-1] if t.endswith("s") and len(t) > 4 else t for t in tokens if t not in STOP and (len(t)>2 or t in ("go", "c#", "c++")))


@lru_cache(maxsize=2048)
def _skills(text: str) -> tuple[str, ...]:
    return tuple(name for name, aliases in SKILLS.items() if any(contains(text, alias) for alias in aliases))


def skills(text: str) -> list[str]:
    return list(_skills(text))


@lru_cache(maxsize=128)
def _requirements(description: str) -> tuple:
    lines = clean(description).splitlines()
    category, explicit = "responsibility", False
    output, fallback = [], []
    seen = set()
    for raw in lines:
        line = raw.strip().strip("•-* \t")
        if not line:
            continue
        heading = line.rstrip(":").strip()
        if len(heading) < 100 and CLOSER.match(heading):
            category = "ignore"
            continue
        # Prefix labels can introduce a criterion on the same line.
        m = re.match(r"^(required|requirements|minimum qualifications|basic qualifications|preferred|nice to have|bonus|responsibilities)\s*:\s*(.+)$", line, re.I)
        if m:
            category = "preferred" if m[1].lower() in ("preferred", "nice to have", "bonus") else "responsibility" if m[1].lower() == "responsibilities" else "required"
            explicit = True
            line = m[2]
        elif len(heading)<80 and re.fullmatch(r"(?:required|requirements|(?:minimum|basic|required|preferred) qualifications|qualifications|what you bring|what you.ll bring|what you have|you have|you.ll have|what we.re looking for|preferred|nice to have|bonus|responsibilities|what you.ll do|you will|you.ll|the role)", heading, re.I):
            category = "preferred" if re.search(r"preferred|nice|bonus", heading, re.I) else "responsibility" if re.search(r"responsibilities|do|you will|you.ll$|the role", heading,re.I) else "required"
            explicit = True
            continue
        if category == "ignore":
            continue
        for clause in re.split(r"(?<=[.!?])\s+(?=[A-Z])|;\s*", line):
            clause = clause.strip()
            normalized = re.sub(r"\s+", " ", clause).casefold()
            if len(clause)<12 or normalized in seen:
                continue
            seen.add(normalized)
            entry = (clause, category)
            if explicit:
                output.append(entry)
            elif skills(clause) or re.match(r"(?:build|design|develop|implement|lead|maintain|operate|own|deliver|manage)\b", clause,re.I):
                fallback.append(entry)
    return tuple(output or fallback)


def extract_requirements(description: str) -> list[dict]:
    result=[]
    for i,(text,category) in enumerate(_requirements(description)):
        result.append({"id":f"req-{i+1}","text":text,"category":category,
                       "weight":3 if category=="required" else 1 if category=="preferred" else 2,
                       "skills":skills(text)})
    return result


def support(requirement: str, quote: str) -> dict:
    requested = skills(requirement)
    negative = bool(NEGATIVE.search(quote))
    observed = [] if negative else skills(quote)
    matched = [s for s in requested if s in observed]
    missing = [s for s in requested if s not in observed]
    # Explicit OR alternatives are not an AND list. Other compound requirements
    # stay partial until every named technology is evidenced.
    alternatives = bool(re.search(r"\bor\b",requirement,re.I)) and len(requested)>1 and not re.search(r"\band\b",requirement,re.I)
    hard_ok = bool(matched) if alternatives else not missing
    rwords, qwords = terms(requirement), terms(quote)
    fraction = len(rwords & qwords)/max(1,len(rwords)) if not negative else 0
    years = re.search(r"(\d+)\+?\s*(?:years?|yrs?)\b",requirement,re.I)
    quantities_ok = not years
    if years:
        quantities_ok = any(int(n)>=int(years[1]) for n in re.findall(r"(\d+)\+?\s*(?:years?|yrs?)\b",quote,re.I))
    negated_requirement = bool(re.search(r"\b(?:not required|no .{0,30}required|do not require)\b",requirement,re.I))
    if negated_requirement:
        status = "uncertain"
    elif negative or not (matched or rwords & qwords):
        status = "missing"
    elif hard_ok and quantities_ok and fraction>=.6:
        status = "supported"
    else:
        status = "partial"
    return {"status":status,"matchedSkills":matched,"missingSkills":[] if alternatives and matched else missing,
            "termFraction":round(fraction,3),"quantityNeedsReview":not quantities_ok,
            "reason":"Explicit negation is not positive evidence." if negative else
                     "Review experience duration against role dates." if not quantities_ok else
                     "Direct wording supports the criterion." if status=="supported" else
                     "Some conditions remain unevidenced." if status=="partial" else "No direct support established."}


def _sentences(text):
    return [s.strip(" \t•-*\n") for s in re.split(r"\n+|[•●]|(?<=[.!?])\s+(?=[A-Z])|;\s*",clean(text)) if len(s.strip())>=8]


@lru_cache(maxsize=64)
def _match(text: str, jd: str, semantic_enabled: bool, k1: float, b: float, rrf_k: int):
    reqs = extract_requirements(jd)
    sentences = _sentences(text)
    index = BM25Index.build([tuple(terms(s)) for s in sentences], k1=k1,b=b)
    digest=hashlib.sha256(text.encode()).hexdigest()
    vectors=None
    if semantic_enabled and sentences and reqs:
        try:
            vectors=semantic.embed_many([(digest,s) for s in sentences]+[("match-req",r["text"]) for r in reqs])
        except Exception:
            vectors=None
    for req in reqs:
        rank=index.rank(tuple(terms(req["text"])))
        rankings=[rank]
        if vectors is not None:
            q=vectors.get(semantic.cache_key("match-req",req["text"]))
            if q:
                sims=[semantic.cosine(q,vectors.get(semantic.cache_key(digest,s),(0.,)*len(q))) for s in sentences]
                rankings.append(sorted(range(len(sentences)),key=lambda i:(-sims[i],i)))
        fused=reciprocal_rank_fusion(rankings,k=rrf_k)
        # Direct lexical witnesses must not be lost because a negated paraphrase
        # ranked above them. The entire short document is verified deterministically.
        scored=[(support(req["text"],s),i) for i,s in enumerate(sentences)]
        order={"missing":0,"uncertain":1,"partial":2,"supported":3}
        best=max(scored,key=lambda x:(order[x[0]["status"]],x[0]["termFraction"],fused.get(x[1],0)),default=None)
        verdict=best[0] if best else support(req["text"],"")
        req.update(verdict)
        req["evidence"] = [{"quote":sentences[best[1]],"sentenceIndex":best[1],"documentHash":digest}] if best and verdict["status"] in ("supported","partial") else []
    assessable=[r for r in reqs if r["status"]!="uncertain"]
    score=round(100*sum(r["weight"]*(1 if r["status"]=="supported" else .5 if r["status"]=="partial" else 0) for r in assessable)/sum(r["weight"] for r in assessable),1) if assessable else None
    return {"score":score,"scoreKind":"document-support-diagnostic","method":VERSION,
            "documentHash":digest,"jobHash":hashlib.sha256(jd.encode()).hexdigest(),
            "requirements":reqs,"semanticAvailable":vectors is not None,
            "counts":{status:sum(r["status"]==status for r in reqs) for status in ("supported","partial","missing","uncertain")},
            "confidence":"limited" if not reqs else "heuristic",
            "notice":"Document evidence diagnostic, not an ATS score or hiring probability. Partial and uncertain criteria need review."}


def match_text(text: str, description: str, *, use_semantic: bool=True, bm25_k1=1.5, bm25_b=.75, rrf_k=60) -> dict:
    normalized="\n".join(re.sub(r"[ \t]+"," ",line).strip() for line in clean(description).splitlines()).strip()
    return deepcopy(_match(text,normalized,use_semantic,bm25_k1,bm25_b,rrf_k))


def compare_pdfs(before: bytes, after: bytes, description: str, **settings) -> dict:
    import pymupdf
    def assess(data):
        with pymupdf.open(stream=data,filetype="pdf") as doc:
            # Sorted extraction may wrap every printed line: preserve adjacent
            # lines as paragraph evidence without reading profile/corpus facts.
            text="\n".join(block[4].replace("\n", " ") for p in doc for block in p.get_text("blocks", sort=True) if block[6] == 0)
        result=match_text(text,description,**settings)
        result["pdfHash"]=hashlib.sha256(data).hexdigest()
        return result
    baseline=assess(before)
    tailored=deepcopy(baseline) if before==after else assess(after)
    return {"before":baseline,"after":tailored,
            "delta":round(tailored["score"]-baseline["score"],1) if baseline["score"] is not None and tailored["score"] is not None else None,
            "changed":before!=after,"notice":baseline["notice"]}
