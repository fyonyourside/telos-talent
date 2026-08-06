#!/usr/bin/env python3
"""Build a local China-focused FDE / business-agent candidate page.

This is intentionally separate from the main talent dashboard. It only uses
public source snippets and labels candidates as China/Chinese-market related
when that signal is explicit in the public text.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.fde_sourcing_agent import build_lead, load_source_hits, rank_leads  # noqa: E402


DEFAULT_SOURCES = REPO_ROOT / "data/china_fde_sources.2026-08-06.json"
DEFAULT_JSON = REPO_ROOT / "data/china_fde_candidates.json"
DEFAULT_HTML = REPO_ROOT / "china_fde_dashboard.html"


CHINA_TERMS = [
    "中国",
    "北京",
    "上海",
    "深圳",
    "杭州",
    "广州",
    "香港",
    "hong kong",
    "china",
    "chinese",
    "baidu ai cloud",
    "qianfan",
    "ernie",
    "qwen",
    "glm",
    "华为",
    "昇腾",
    "盘古",
    "百度",
    "千帆",
    "通义",
    "智谱",
    "月之暗面",
    "minimax",
    "dify",
    "langgenius",
    "火山",
    "豆包",
    "国家电网",
    "中国知网",
]


def has_cjk(text: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", text) is not None


def china_signal(source_text: str, lead: dict[str, Any]) -> tuple[bool, str]:
    text = " ".join(
        str(v or "")
        for v in [
            source_text,
            lead.get("name"),
            lead.get("location"),
            lead.get("current"),
            lead.get("bg"),
            lead.get("notes"),
        ]
    )
    lowered = text.lower()
    hits = [term for term in CHINA_TERMS if term in lowered]
    if has_cjk(text):
        hits.append("中文公开资料/姓名")
    seen = []
    for hit in hits:
        if hit not in seen:
            seen.append(hit)
    return bool(seen), "、".join(seen[:6])


def build_china_candidates(source_path: Path, min_score: int) -> list[dict[str, Any]]:
    hits = load_source_hits(source_path)
    candidates = []
    for hit in hits:
        lead = build_lead(hit, today=_dt.date.today().isoformat())
        ok, reason = china_signal(hit.haystack, lead)
        if not ok or int(lead.get("score") or 0) < min_score:
            continue
        lead["china_signal"] = reason
        lead["next_action"] = screen_next_action(lead)
        candidates.append(lead)
    return rank_leads(candidates, min_score=min_score)


def screen_next_action(lead: dict[str, Any]) -> str:
    score = int(lead.get("score") or 0)
    if score >= 9:
        return "优先外联：验证是否愿意看机会、是否能客户沟通、是否完整 owner 过业务 Agent 上线。"
    if score >= 7:
        return "二线外联：重点确认工程 hands-on、真实客户交付和 Agent harness 深度。"
    return "先补调研：确认是不是本人搭建 Agent，而不是偏售前/产品/课程。"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def strip_trailing_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def render_html(candidates: list[dict[str, Any]], source_path: Path) -> str:
    updated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    cards = "\n".join(render_card(c) for c in candidates)
    data = json.dumps(candidates, ensure_ascii=False)
    source_label = str(source_path)
    try:
        source_label = str(source_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        pass
    counts = {
        tier: sum(1 for c in candidates if c.get("tier") == tier)
        for tier in ["S", "A", "B", "C"]
    }
    return strip_trailing_whitespace(f"""<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>中国 FDE / 业务 Agent 候选人</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#081e21; --panel:#0f3438; --panel2:#123f45; --text:#eef7f4;
      --muted:rgba(238,247,244,.62); --line:rgba(255,255,255,.1);
      --gold:#f2b84b; --red:#ff8068; --blue:#7ab7ff; --green:#77d996;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }}
    header {{ position:sticky; top:0; z-index:3; padding:22px 28px; background:linear-gradient(135deg,#061719,#0c3035); border-bottom:1px solid var(--line); }}
    h1 {{ margin:0 0 8px; font-size:22px; letter-spacing:.02em; }}
    .sub {{ color:var(--muted); font-size:13px; line-height:1.7; max-width:980px; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
    .stat {{ padding:8px 12px; border:1px solid var(--line); border-radius:999px; background:rgba(255,255,255,.04); font-size:12px; }}
    .toolbar {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }}
    input, button {{ border:1px solid var(--line); border-radius:10px; padding:9px 11px; background:rgba(255,255,255,.06); color:var(--text); }}
    input {{ min-width:280px; outline:none; }}
    button {{ cursor:pointer; }}
    button.active {{ border-color:var(--gold); color:var(--gold); }}
    main {{ padding:24px 28px 56px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:14px; }}
    .card {{ border:1px solid var(--line); border-radius:16px; padding:16px; background:var(--panel); box-shadow:0 12px 30px rgba(0,0,0,.18); }}
    .card:hover {{ background:var(--panel2); }}
    .top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .name {{ font-weight:700; font-size:16px; line-height:1.35; }}
    .tier {{ flex:0 0 auto; font-weight:700; border-radius:999px; padding:4px 9px; border:1px solid var(--line); }}
    .tier.S {{ color:var(--red); border-color:rgba(255,128,104,.45); }}
    .tier.A {{ color:var(--gold); border-color:rgba(242,184,75,.45); }}
    .tier.B {{ color:var(--blue); border-color:rgba(122,183,255,.45); }}
    .meta {{ color:var(--muted); font-size:12px; margin-top:7px; line-height:1.55; }}
    .bg {{ font-size:13px; line-height:1.7; margin-top:12px; color:rgba(238,247,244,.86); }}
    .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }}
    .chip {{ font-size:11px; color:var(--green); border:1px solid rgba(119,217,150,.25); border-radius:999px; padding:4px 7px; }}
    .why {{ margin-top:12px; padding-top:12px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; line-height:1.6; }}
    a {{ color:#9bd5ff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .empty {{ color:var(--muted); padding:60px 0; text-align:center; display:none; }}
  </style>
</head>
<body>
  <header>
    <h1>中国 FDE / 业务 Agent 候选人</h1>
    <div class="sub">
      本地页面，只基于公开搜索/profile 片段生成；“中国”指公开资料中明确出现中国/香港/中文履历/中国市场或中国公司项目信号，不做私人身份推断。
      来源：{html.escape(source_label)}；更新时间：{updated}。
    </div>
    <div class="stats">
      <span class="stat">总数 {len(candidates)}</span>
      <span class="stat">S {counts["S"]}</span>
      <span class="stat">A {counts["A"]}</span>
      <span class="stat">B {counts["B"]}</span>
    </div>
    <div class="toolbar">
      <input id="q" placeholder="搜索姓名 / 技能 / 公司 / 关键词">
      <button data-tier="all" class="active">全部</button>
      <button data-tier="S">S</button>
      <button data-tier="A">A</button>
      <button data-tier="B">B</button>
    </div>
  </header>
  <main>
    <div class="grid" id="grid">{cards}</div>
    <div class="empty" id="empty">没有匹配结果</div>
  </main>
  <script>
    window.CHINA_FDE_CANDIDATES = {data};
    const q = document.getElementById('q');
    const buttons = [...document.querySelectorAll('button[data-tier]')];
    const cards = [...document.querySelectorAll('.card')];
    let tier = 'all';
    function applyFilter() {{
      const query = q.value.trim().toLowerCase();
      let visible = 0;
      cards.forEach(card => {{
        const okTier = tier === 'all' || card.dataset.tier === tier;
        const okQuery = !query || card.textContent.toLowerCase().includes(query);
        const show = okTier && okQuery;
        card.style.display = show ? '' : 'none';
        if (show) visible++;
      }});
      document.getElementById('empty').style.display = visible ? 'none' : 'block';
    }}
    q.addEventListener('input', applyFilter);
    buttons.forEach(btn => btn.addEventListener('click', () => {{
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      tier = btn.dataset.tier;
      applyFilter();
    }}));
  </script>
</body>
</html>
""")


def render_card(candidate: dict[str, Any]) -> str:
    url = candidate.get("linkedin") or candidate.get("github") or candidate.get("website") or ""
    skills = "".join(f'<span class="chip">{html.escape(str(skill))}</span>' for skill in candidate.get("skills", [])[:10])
    bg = html.escape(candidate.get("bg") or "")
    if len(bg) > 520:
        bg = bg[:517] + "..."
    name = html.escape(candidate.get("name") or "Unknown")
    tier = html.escape(candidate.get("tier") or "C")
    score = int(candidate.get("score") or 0)
    current = html.escape(candidate.get("current") or "—")
    location = html.escape(candidate.get("location") or "—")
    china_signal = html.escape(candidate.get("china_signal") or "—")
    why = html.escape(candidate.get("priority_reason") or "")
    next_action = html.escape(candidate.get("next_action") or "")
    link = f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">打开公开资料</a>' if url else "无链接"
    searchable = html.escape(json.dumps(candidate, ensure_ascii=False))
    return f"""
    <article class="card" data-tier="{tier}" data-search="{searchable}">
      <div class="top">
        <div>
          <div class="name">{name}</div>
          <div class="meta">{current} · {location}</div>
        </div>
        <div class="tier {tier}">{tier} · {score}/10</div>
      </div>
      <div class="bg">{bg}</div>
      <div class="chips">{skills}</div>
      <div class="why">
        <div><strong>中国/华语信号：</strong>{china_signal}</div>
        <div><strong>命中原因：</strong>{why}</div>
        <div><strong>下一步：</strong>{next_action}</div>
        <div><strong>链接：</strong>{link}</div>
      </div>
    </article>
    """


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default=str(DEFAULT_SOURCES))
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--html", default=str(DEFAULT_HTML))
    parser.add_argument("--min-score", type=int, default=5)
    args = parser.parse_args()

    source_path = Path(args.sources)
    candidates = build_china_candidates(source_path, args.min_score)
    write_json(Path(args.json), {"generated_at": _dt.datetime.now().isoformat(timespec="seconds"), "source": str(source_path), "candidates": candidates})
    Path(args.html).write_text(render_html(candidates, source_path), encoding="utf-8")
    print(json.dumps({"candidates": len(candidates), "json": args.json, "html": args.html}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
