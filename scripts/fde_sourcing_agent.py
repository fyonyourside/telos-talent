#!/usr/bin/env python3
"""Find and rank business-agent / FDE candidates from public sources.

The script is intentionally dependency-free so it can run locally, in GitHub
Actions, or from an exported recruiter search without extra setup.

Typical usage:

  python3 scripts/fde_sourcing_agent.py queries
  python3 scripts/fde_sourcing_agent.py ingest --input data/fde_sources.sample.json
  python3 scripts/fde_sourcing_agent.py github --limit 20
  python3 scripts/fde_sourcing_agent.py apply --input out/fde_candidates.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEADS_FILE = REPO_ROOT / "leads.json"
DEFAULT_DASHBOARD_FILE = REPO_ROOT / "dashboard.html"


SEARCH_QUERIES = [
    {
        "channel": "LinkedIn / Google",
        "query": '("Forward Deployed Engineer" OR "AI Solutions Engineer" OR "LLM Application Engineer") '
        '("LangGraph" OR "LangChain" OR "RAG" OR "tool calling") '
        '("enterprise" OR "customer" OR "B2B" OR "production")',
        "why": "FDE / solutions titles plus agent implementation and enterprise delivery signals.",
    },
    {
        "channel": "LinkedIn / Google",
        "query": '("agent evals" OR "eval harness" OR "LangSmith" OR "observability") '
        '("LangGraph" OR "agentic workflow")',
        "why": "Find candidates who have shipped agent harnesses rather than demos only.",
    },
    {
        "channel": "GitHub",
        "query": '"LangGraph" "RAG" "agent" "eval harness"',
        "why": "Public builders with code artifacts around production agent reliability.",
    },
    {
        "channel": "GitHub",
        "query": '"customer support agent" "LangGraph" "FastAPI"',
        "why": "Business-agent pattern: support workflow, tools, backend integration.",
    },
    {
        "channel": "脉脉 / BOSS / 猎聘",
        "query": "大模型 FDE Agent Workflow 客户 交付",
        "why": "China-market FDE wording used by model companies and cloud vendors.",
    },
    {
        "channel": "脉脉 / BOSS / 猎聘",
        "query": "大模型解决方案工程师 RAG Agent 企业AI",
        "why": "Find customer-facing LLM app engineers whose title is not literally FDE.",
    },
]


KEYWORD_GROUPS = {
    "customer_facing": [
        "forward deployed",
        "fde",
        "solutions engineer",
        "solution architect",
        "customer-facing",
        "customer facing",
        "customer",
        "customers",
        "client-facing",
        "client",
        "clients",
        "stakeholder",
        "stakeholders",
        "enterprise client",
        "enterprise customer",
        "delivery",
        "production deployment",
        "solution architecture",
        "key accounts",
        "poc",
        "mvp",
        "b2b",
        "售前",
        "解决方案",
        "交付",
        "客户",
        "驻场",
        "企业客户",
    ],
    "agent_building": [
        "ai agent",
        "agentic",
        "agentic workflow",
        "llm application",
        "llm applications",
        "rag",
        "retrieval-augmented",
        "multi-agent",
        "multi agent",
        "langgraph",
        "langchain",
        "llamaindex",
        "autogen",
        "crewai",
        "tool calling",
        "function calling",
        "mcp",
        "model context protocol",
        "workflow",
        "智能体",
        "工具调用",
        "工作流",
        "多智能体",
    ],
    "business_domain": [
        "customer support",
        "sales agent",
        "crm",
        "salesforce",
        "zendesk",
        "servicenow",
        "erp",
        "bi",
        "business automation",
        "workflow automation",
        "document intelligence",
        "客服",
        "销售",
        "工单",
        "知识库",
        "数据分析",
        "业务流程",
        "企业应用",
    ],
    "harness_reliability": [
        "eval harness",
        "agent eval",
        "agent evals",
        "evaluation framework",
        "langsmith",
        "ragas",
        "observability",
        "production readiness",
        "reliability",
        "tracing",
        "trace",
        "guardrail",
        "guardrails",
        "regression",
        "trajectory",
        "evals",
        "llm evaluation",
        "human-in-the-loop",
        "human in the loop",
        "测试集",
        "评测",
        "可观测",
        "回归测试",
        "轨迹",
        "护栏",
    ],
    "engineering": [
        "python",
        "typescript",
        "fastapi",
        "node.js",
        "react",
        "postgres",
        "redis",
        "docker",
        "kubernetes",
        "k8s",
        "aws",
        "azure",
        "gcp",
        "后端",
        "全栈",
        "工程",
        "部署",
        "上线",
    ],
    "model_company": [
        "openai",
        "anthropic",
        "langchain",
        "dify",
        "langgenius",
        "coze",
        "火山方舟",
        "豆包",
        "字节",
        "蚂蚁数科",
        "阿里云",
        "通义",
        "腾讯云",
        "混元",
        "智谱",
        "minimax",
        "moonshot",
        "kimi",
        "月之暗面",
        "零一万物",
    ],
}


NEGATIVE_KEYWORDS = [
    "internship",
    "intern ",
    "student",
    "fresh graduate",
    "prompt engineer only",
    "content creator",
    "ai influencer",
    "课程",
    "培训",
    "小白",
    "实习",
    "在校",
]


GROUP_WEIGHTS = {
    "customer_facing": 2,
    "agent_building": 2,
    "business_domain": 2,
    "harness_reliability": 2,
    "engineering": 1,
    "model_company": 1,
}


@dataclass
class SourceHit:
    """One public search/profile hit."""

    name: str
    url: str = ""
    title: str = ""
    snippet: str = ""
    platform: str = "web"
    location: str = ""
    current: str = ""
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SourceHit":
        name = str(data.get("name") or data.get("title") or data.get("login") or "").strip()
        title = str(data.get("role") or data.get("headline") or data.get("title") or "").strip()
        snippet = str(data.get("snippet") or data.get("content") or data.get("bio") or data.get("description") or "").strip()
        url = str(data.get("url") or data.get("html_url") or data.get("linkedin") or data.get("github") or "").strip()
        platform = str(data.get("platform") or infer_platform(url) or "web").strip()
        current = str(data.get("current") or data.get("company") or "").strip()
        return cls(
            name=name,
            url=url,
            title=title,
            snippet=snippet,
            platform=platform,
            location=str(data.get("location") or "").strip(),
            current=current,
            source=str(data.get("source") or platform).strip(),
            extra={k: v for k, v in data.items() if k not in {"name", "title", "role", "headline", "snippet", "content", "bio", "description", "url", "html_url", "linkedin", "github", "platform", "location", "current", "company", "source"}},
        )

    @property
    def haystack(self) -> str:
        return " ".join(
            p
            for p in [
                self.name,
                self.title,
                self.current,
                self.location,
                self.snippet,
                json.dumps(self.extra, ensure_ascii=False, sort_keys=True),
            ]
            if p
        )


def infer_platform(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "github.com" in host:
        return "github"
    if "linkedin.com" in host:
        return "linkedin"
    if "maimai" in host:
        return "maimai"
    if "zhihu" in host:
        return "zhihu"
    if "x.com" in host or "twitter.com" in host:
        return "twitter"
    return "web" if url else ""


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    lowered = normalize_text(text)
    hits = []
    for kw in keywords:
        needle = kw.lower()
        if is_keyword_match(lowered, needle):
            hits.append(kw)
    return hits


def is_keyword_match(lowered_text: str, lowered_keyword: str) -> bool:
    """Match CJK keywords by substring and ASCII keywords by token boundary.

    This avoids false positives like the business-domain keyword "bi" matching
    the word "bio" in GitHub profile snippets.
    """

    if re.search(r"[\u4e00-\u9fff]", lowered_keyword):
        return lowered_keyword in lowered_text
    pattern = r"(?<![a-z0-9])" + re.escape(lowered_keyword) + r"(?![a-z0-9])"
    return re.search(pattern, lowered_text) is not None


def score_hit(hit: SourceHit) -> dict[str, Any]:
    """Return score details for one source hit."""

    text = hit.haystack
    group_hits: dict[str, list[str]] = {
        group: keyword_hits(text, words) for group, words in KEYWORD_GROUPS.items()
    }
    negative_hits = keyword_hits(text, NEGATIVE_KEYWORDS)

    raw = 0
    for group, hits in group_hits.items():
        if hits:
            raw += GROUP_WEIGHTS[group]
            if len(hits) >= 3 and group in {"agent_building", "harness_reliability"}:
                raw += 1

    # Bonus for the complete business-agent pattern: customer + agent + engineering.
    if group_hits["customer_facing"] and group_hits["agent_building"] and group_hits["engineering"]:
        raw += 2
    if group_hits["business_domain"] and group_hits["harness_reliability"]:
        raw += 1

    raw -= min(3, len(negative_hits))
    score = max(0, min(10, raw))
    if score >= 9:
        tier = "S"
    elif score >= 7:
        tier = "A"
    elif score >= 5:
        tier = "B"
    else:
        tier = "C"

    reasons = []
    for group, hits in group_hits.items():
        if hits:
            reasons.append(f"{group}: {', '.join(hits[:5])}")
    if negative_hits:
        reasons.append(f"negative: {', '.join(negative_hits[:5])}")

    return {
        "score": score,
        "tier": tier,
        "group_hits": group_hits,
        "negative_hits": negative_hits,
        "reasons": reasons,
    }


def stable_id(hit: SourceHit) -> str:
    url = hit.url.rstrip("/")
    parsed = urllib.parse.urlparse(url)
    platform = hit.platform or infer_platform(url) or "web"
    if platform == "github" and parsed.path.strip("/"):
        handle = urllib.parse.unquote(parsed.path.strip("/").split("/")[0])
        return f"gh-{slugify(handle)}"
    if platform == "linkedin" and parsed.path.strip("/"):
        handle = urllib.parse.unquote(parsed.path.strip("/").split("/")[-1])
        return f"li-{slugify(handle)}"

    base = url or f"{hit.name} {hit.current} {hit.title}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    stem = slugify(hit.name)[:28] or "candidate"
    return f"{platform}-{stem}-{digest}"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "unknown"


def extract_skills(group_hits: dict[str, list[str]]) -> list[str]:
    picked = []
    for group in ["agent_building", "harness_reliability", "business_domain", "engineering"]:
        for hit in group_hits.get(group, []):
            label = normalize_skill(hit)
            if label and label not in picked:
                picked.append(label)
            if len(picked) >= 10:
                return picked
    return picked


def normalize_skill(skill: str) -> str:
    aliases = {
        "ai agent": "AI Agent",
        "llm application": "LLM Application",
        "llm applications": "LLM Application",
        "rag": "RAG",
        "mcp": "MCP",
        "crm": "CRM",
        "erp": "ERP",
        "bi": "BI",
        "fastapi": "FastAPI",
        "aws": "AWS",
        "azure": "Azure",
        "gcp": "GCP",
        "typescript": "TypeScript",
        "kubernetes": "Kubernetes",
        "docker": "Docker",
        "postgres": "Postgres",
        "postgresql": "PostgreSQL",
        "redis": "Redis",
        "react": "React",
        "langgraph": "LangGraph",
        "langchain": "LangChain",
        "langsmith": "LangSmith",
        "tool calling": "Tool Calling",
        "function calling": "Function Calling",
        "agentic workflow": "Agentic Workflow",
        "multi-agent": "Multi-Agent",
        "multi agent": "Multi-Agent",
        "eval harness": "Eval Harness",
        "agent eval": "Agent Eval",
        "agent evals": "Agent Eval",
        "observability": "Observability",
        "human-in-the-loop": "Human-in-the-loop",
        "human in the loop": "Human-in-the-loop",
        "customer support": "Customer Support Agent",
        "business automation": "Business Automation",
        "workflow automation": "Workflow Automation",
    }
    lowered = skill.lower()
    if lowered in aliases:
        return aliases[lowered]
    if skill.isascii():
        return skill[:1].upper() + skill[1:]
    return skill


def build_lead(hit: SourceHit, today: str | None = None) -> dict[str, Any]:
    details = score_hit(hit)
    today = today or _dt.date.today().isoformat()
    group_hits = details["group_hits"]

    url_fields: dict[str, str] = {}
    if hit.platform == "github":
        url_fields["github"] = hit.url
    elif hit.platform == "linkedin":
        url_fields["linkedin"] = hit.url
    elif hit.url:
        url_fields["website"] = hit.url

    current = hit.current or extract_current_from_title(hit.title)
    bg_parts = [p for p in [hit.title, hit.snippet] if p]
    bg = "；".join(bg_parts)
    if len(bg) > 420:
        bg = bg[:417] + "..."

    reasons = "; ".join(details["reasons"])
    if len(reasons) > 420:
        reasons = reasons[:417] + "..."

    return {
        "id": stable_id(hit),
        "name": hit.name or "Unknown candidate",
        "role": "FDE (交付)",
        "score": details["score"],
        "tier": details["tier"],
        "location": hit.location,
        "current": current,
        "bg": bg,
        "skills": extract_skills(group_hits),
        "voice": "voice" in normalize_text(hit.haystack) or "语音" in hit.haystack,
        "xiaohongshu": None,
        **url_fields,
        "contact": "",
        "source": hit.source or f"{hit.platform}_source",
        "platform": hit.platform,
        "notes": f"FDE sourcing agent 初筛：{reasons}",
        "is_academic": False,
        "is_eng": bool(group_hits["engineering"] or group_hits["agent_building"]),
        "is_pm": bool(group_hits["customer_facing"] or group_hits["business_domain"]),
        "is_algo": False,
        "date_found": today,
        "status": "new",
        "note": "",
        "priority": details["score"] >= 8,
        "founder_signal": "founder" in normalize_text(hit.haystack) or "创始" in hit.haystack,
        "availability_risk": "",
        "priority_reason": reasons,
        "research_summary": summarize_hit(hit, details),
        "research_urls": [hit.url] if hit.url else [],
        "research_updated": today,
        "org_account_signal": False,
        "contact_research_status": "not_checked",
        "contact_checked_paths": [],
        "contact_found_channels": [hit.platform] if hit.url else [],
        "contact_missing_channels": [],
        "contact_research_summary": "未做联系方式深挖；仅基于公开搜索/profile 片段初筛。",
        "contact_next_step": "用 LinkedIn/脉脉/内推路径验证客户沟通经验、生产 Agent ownership、eval harness 经验。",
        "contact_sources": [hit.url] if hit.url else [],
        "contact_research_updated": "",
        "talent_track": "fde",
        "is_fde": True,
        "track_rank": 999,
        "custom_name": "",
        "track_manual": False,
        "manual_low_priority": False,
        "is_builder": bool(group_hits["agent_building"]),
        "tier_manual": False,
    }


def extract_current_from_title(title: str) -> str:
    if "@" in title:
        return title.split("@", 1)[1].split("|", 1)[0].strip()
    return ""


def summarize_hit(hit: SourceHit, details: dict[str, Any]) -> str:
    snippets = []
    if hit.title:
        snippets.append(hit.title)
    if hit.current:
        snippets.append(hit.current)
    if hit.snippet:
        snippets.append(hit.snippet)
    summary = " | ".join(snippets)
    if len(summary) > 360:
        summary = summary[:357] + "..."
    return f"Public source hit scored {details['score']}/10 ({details['tier']}): {summary}"


def load_source_hits(path: Path) -> list[SourceHit]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        if "results" in payload:
            rows = payload["results"]
        elif "hits" in payload:
            rows = payload["hits"]
        elif "leads" in payload:
            rows = payload["leads"]
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"Unsupported input JSON shape in {path}")

    hits = [SourceHit.from_mapping(row) for row in rows if isinstance(row, dict)]
    return [h for h in hits if h.name or h.url or h.snippet]


def rank_leads(leads: list[dict[str, Any]], min_score: int = 0) -> list[dict[str, Any]]:
    filtered = [lead for lead in leads if int(lead.get("score") or 0) >= min_score]
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    return sorted(
        filtered,
        key=lambda lead: (
            tier_order.get(lead.get("tier", "C"), 9),
            -int(lead.get("score") or 0),
            lead.get("name") or "",
        ),
    )


def assign_track_ranks(leads: list[dict[str, Any]]) -> None:
    fde = [lead for lead in leads if lead.get("talent_track") == "fde" and lead.get("status") not in ("pass", "converted")]
    ranked_ids = [lead["id"] for lead in rank_leads(fde)]
    id_to_rank = {lead_id: i + 1 for i, lead_id in enumerate(ranked_ids)}
    for lead in leads:
        if lead.get("id") in id_to_rank and not lead.get("track_manual"):
            lead["track_rank"] = id_to_rank[lead["id"]]


def merge_leads(existing_data: dict[str, Any], new_leads: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, int]]:
    leads = list(existing_data.get("leads", []))
    by_id = {lead.get("id"): lead for lead in leads}
    stats = {"added": 0, "updated": 0, "skipped": 0}

    for new in new_leads:
        lead_id = new.get("id")
        if not lead_id:
            stats["skipped"] += 1
            continue
        if lead_id in by_id:
            existing = by_id[lead_id]
            if int(new.get("score") or 0) > int(existing.get("score") or 0):
                preserve = {
                    k: existing.get(k)
                    for k in ["status", "note", "priority", "custom_name", "track_manual", "manual_low_priority", "tier_manual"]
                    if k in existing
                }
                existing.update(new)
                existing.update({k: v for k, v in preserve.items() if v not in (None, "")})
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            leads.append(new)
            by_id[lead_id] = new
            stats["added"] += 1

    assign_track_ranks(leads)
    meta = dict(existing_data.get("meta", {}))
    meta["last_updated"] = _dt.date.today().isoformat()
    meta["total"] = len(leads)
    meta["version"] = int(meta.get("version") or 1)
    meta["pending_feishu_notify"] = True
    return {"meta": meta, "leads": leads}, stats


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def update_dashboard_data(dashboard_path: Path, leads_data: dict[str, Any]) -> None:
    html = dashboard_path.read_text(encoding="utf-8")
    marker = "const LEADS_DATA = "
    start = html.find(marker)
    if start == -1:
        raise RuntimeError(f"Could not find {marker!r} in {dashboard_path}")
    obj_start = start + len(marker)
    obj_end = find_js_object_end(html, obj_start)
    replacement = json.dumps(leads_data, ensure_ascii=False, indent=2)
    html = html[:obj_start] + replacement + html[obj_end:]
    dashboard_path.write_text(html, encoding="utf-8")


def find_js_object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                if end < len(text) and text[end] == ";":
                    end += 1
                return end
    raise RuntimeError("Unterminated LEADS_DATA object")


def github_api(path: str, token: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "telos-fde-sourcing-agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API HTTP {e.code}: {body}") from None


def github_search_hits(query: str, limit: int, token: str = "", sleep_seconds: float = 0.2) -> list[SourceHit]:
    per_page = min(50, max(1, limit))
    payload = github_api(
        "/search/repositories",
        token=token,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
    )
    hits: dict[str, SourceHit] = {}
    for repo in payload.get("items", [])[:limit]:
        owner = repo.get("owner") or {}
        login = owner.get("login") or ""
        if not login:
            continue
        if sleep_seconds:
            time.sleep(sleep_seconds)
        try:
            user = github_api(f"/users/{login}", token=token)
        except RuntimeError:
            user = {}
        profile_url = user.get("html_url") or owner.get("html_url") or ""
        repo_desc = repo.get("description") or ""
        user_bio = user.get("bio") or ""
        name = user.get("name") or login
        company = (user.get("company") or "").lstrip("@")
        location = user.get("location") or ""
        snippet = (
            f"GitHub repo {repo.get('full_name')} ({repo.get('stargazers_count', 0)} stars): "
            f"{repo_desc}. Profile bio: {user_bio}"
        )
        if login in hits:
            hits[login].snippet += " | " + snippet
        else:
            hits[login] = SourceHit(
                name=f"{name} / {login}" if name != login else login,
                url=profile_url,
                title=user_bio,
                snippet=snippet,
                platform="github",
                location=location,
                current=company,
                source=f"github_search: {query}",
                extra={
                    "followers": user.get("followers"),
                    "public_repos": user.get("public_repos"),
                    "repo": repo.get("full_name"),
                    "repo_stars": repo.get("stargazers_count"),
                },
            )
    return list(hits.values())


def render_markdown(leads: list[dict[str, Any]]) -> str:
    lines = ["# FDE / Business Agent sourcing results", ""]
    if not leads:
        lines.append("_No candidates matched the threshold._")
        return "\n".join(lines) + "\n"
    for i, lead in enumerate(leads, 1):
        url = lead.get("linkedin") or lead.get("github") or lead.get("website") or ""
        link = f" — {url}" if url else ""
        lines.extend(
            [
                f"## {i}. {lead.get('name')} ({lead.get('tier')} · {lead.get('score')}/10){link}",
                f"- Current: {lead.get('current') or '—'}",
                f"- Location: {lead.get('location') or '—'}",
                f"- Skills: {', '.join(lead.get('skills') or []) or '—'}",
                f"- Why: {lead.get('priority_reason') or '—'}",
                f"- Next: {lead.get('contact_next_step') or '—'}",
                "",
            ]
        )
    return "\n".join(lines)


def command_queries(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(SEARCH_QUERIES, ensure_ascii=False, indent=2))
        return 0
    for item in SEARCH_QUERIES:
        print(f"[{item['channel']}] {item['query']}")
        print(f"  - {item['why']}")
    return 0


def command_ingest(args: argparse.Namespace) -> int:
    hits = load_source_hits(Path(args.input))
    leads = rank_leads([build_lead(hit) for hit in hits], min_score=args.min_score)
    if args.output:
        write_json(Path(args.output), leads)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(render_markdown(leads), encoding="utf-8")
    print(json.dumps({"candidates": len(leads), "top": leads[: args.preview]}, ensure_ascii=False, indent=2))
    return 0


def command_github(args: argparse.Namespace) -> int:
    token = args.github_token or os.environ.get("GITHUB_TOKEN", "")
    hits = github_search_hits(args.query, args.limit, token=token, sleep_seconds=args.sleep)
    leads = rank_leads([build_lead(hit) for hit in hits], min_score=args.min_score)
    if args.output:
        write_json(Path(args.output), leads)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(render_markdown(leads), encoding="utf-8")
    print(json.dumps({"query": args.query, "hits": len(hits), "candidates": len(leads), "top": leads[: args.preview]}, ensure_ascii=False, indent=2))
    return 0


def command_apply(args: argparse.Namespace) -> int:
    with Path(args.input).open(encoding="utf-8") as f:
        new_leads = json.load(f)
    if not isinstance(new_leads, list):
        raise ValueError("--input must contain a JSON list of lead drafts")

    leads_path = Path(args.leads)
    with leads_path.open(encoding="utf-8") as f:
        existing = json.load(f)
    merged, stats = merge_leads(existing, new_leads)

    if args.dry_run:
        print(json.dumps({"dry_run": True, **stats, "total": len(merged.get("leads", []))}, ensure_ascii=False, indent=2))
        return 0

    write_json(leads_path, merged)
    if args.dashboard:
        update_dashboard_data(Path(args.dashboard), merged)
    print(json.dumps({**stats, "total": len(merged.get("leads", []))}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("queries", help="Print recommended sourcing search queries")
    q.add_argument("--json", action="store_true", help="Emit query plan as JSON")
    q.set_defaults(func=command_queries)

    ingest = sub.add_parser("ingest", help="Score search/profile hits from a JSON file")
    ingest.add_argument("--input", required=True, help="JSON file with results/hits list")
    ingest.add_argument("--output", help="Write lead drafts JSON")
    ingest.add_argument("--markdown", help="Write human-readable markdown")
    ingest.add_argument("--min-score", type=int, default=5)
    ingest.add_argument("--preview", type=int, default=5)
    ingest.set_defaults(func=command_ingest)

    gh = sub.add_parser("github", help="Search public GitHub repositories and score owners")
    gh.add_argument("--query", default='"LangGraph" "RAG" "agent" "eval harness"', help="GitHub repository search query")
    gh.add_argument("--limit", type=int, default=20)
    gh.add_argument("--min-score", type=int, default=5)
    gh.add_argument("--output", help="Write lead drafts JSON")
    gh.add_argument("--markdown", help="Write human-readable markdown")
    gh.add_argument("--github-token", default="", help="Optional token; defaults to GITHUB_TOKEN")
    gh.add_argument("--sleep", type=float, default=0.2, help="Delay between GitHub user profile calls")
    gh.add_argument("--preview", type=int, default=5)
    gh.set_defaults(func=command_github)

    apply = sub.add_parser("apply", help="Merge lead drafts into leads.json and dashboard")
    apply.add_argument("--input", required=True, help="Lead drafts JSON from ingest/github")
    apply.add_argument("--leads", default=str(DEFAULT_LEADS_FILE))
    apply.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD_FILE))
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=command_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
