# FDE / Business Agent sourcing agent

`scripts/fde_sourcing_agent.py` helps build the FDE / business-agent recruiting lane from public sources.

It is designed for the role profile:

- can talk to customers and unpack business workflows;
- can build agents hands-on;
- has production engineering ability;
- has Agent harness / eval / tracing / observability experience;
- has B2B workflow, CRM/ERP/helpdesk/BI/support/sales-agent experience.

The script uses only Python's standard library.

## 1. Generate search queries

```bash
python3 scripts/fde_sourcing_agent.py queries
```

Use these queries in LinkedIn, Google, 脉脉, BOSS, 猎聘, GitHub, or technical communities.

## 2. Score exported search results

Create a JSON file like `data/fde_sources.sample.json`:

```json
{
  "results": [
    {
      "name": "Candidate Name",
      "title": "Forward Deployed AI Engineer | LangGraph | RAG",
      "url": "https://linkedin.com/in/example",
      "platform": "linkedin",
      "location": "北京",
      "current": "Example AI Startup",
      "snippet": "Built production customer support agents for enterprise clients with tool calling, eval harness, LangSmith tracing, FastAPI, and CRM integrations.",
      "source": "linkedin_search"
    }
  ]
}
```

Then run:

```bash
python3 scripts/fde_sourcing_agent.py ingest \
  --input data/fde_sources.sample.json \
  --output out/fde_candidates.json \
  --markdown out/fde_candidates.md \
  --min-score 5
```

## 3. Search public GitHub builders

```bash
python3 scripts/fde_sourcing_agent.py github \
  --query '"LangGraph" "RAG" "agent" "eval harness"' \
  --limit 20 \
  --output out/github_fde_candidates.json \
  --markdown out/github_fde_candidates.md
```

Set `GITHUB_TOKEN` to increase rate limits:

```bash
GITHUB_TOKEN=... python3 scripts/fde_sourcing_agent.py github --limit 50
```

GitHub results are best treated as builder leads. The agent intentionally asks you to verify customer-facing experience before outreach.

## 4. Merge lead drafts into the talent dashboard

Preview first:

```bash
python3 scripts/fde_sourcing_agent.py apply \
  --input out/fde_candidates.json \
  --dry-run
```

Apply to `leads.json` and refresh embedded `LEADS_DATA` in `dashboard.html`:

```bash
python3 scripts/fde_sourcing_agent.py apply \
  --input out/fde_candidates.json
```

The merge preserves manual state on existing leads, including:

- `status`
- `note`
- `priority`
- `custom_name`
- manual track / tier flags

## 5. Scoring model

The agent scores each public hit across six groups:

| Signal | Examples |
| --- | --- |
| Customer-facing | FDE, solutions engineer, enterprise customer, B2B, 交付, 客户 |
| Agent building | LangGraph, LangChain, RAG, MCP, tool calling, multi-agent |
| Business domain | CRM, ERP, Salesforce, Zendesk, customer support, sales agent, BI |
| Harness reliability | eval harness, LangSmith, tracing, guardrails, trajectory eval |
| Engineering | Python, TypeScript, FastAPI, Docker, Kubernetes, Postgres |
| Model-company context | Dify, Coze, 豆包, 智谱, MiniMax, Kimi, OpenAI, Anthropic |

Tiering:

- `S`: 9-10, likely strong FDE / business-agent fit
- `A`: 7-8, strong builder or delivery signal, verify missing dimension
- `B`: 5-6, promising but likely needs screening
- `C`: below 5, keep out of the main outreach pool

