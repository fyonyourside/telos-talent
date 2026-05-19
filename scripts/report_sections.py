"""Shared blocks for daily Feishu / text reports — four hiring tracks only."""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

TRACK_ORDER = ("harness_eng", "research_eng", "pm", "fde")
TRACK_META: Dict[str, dict] = {
    "harness_eng": {
        "label": "Harness 工程",
        "short": "Harness",
        "blurb": "Infra / Agent 框架 / 运行时",
    },
    "research_eng": {
        "label": "Research 算法/语音",
        "short": "Research",
        "blurb": "语音模型训练 · CosyVoice / FunASR 等",
    },
    "pm": {
        "label": "Model & Agent PM",
        "short": "PM",
        "blurb": "0-1 Agent · 测评 · 数据迭代 · 应用/B2B 产品向",
    },
    "fde": {
        "label": "FDE 交付",
        "short": "FDE",
        "blurb": "客户侧交付 · B2B 应用落地（多数不玩 GitHub，库内偏少）",
    },
}
TIER_BADGE = {"S": "🏆 S", "A": "🔵 A", "B": "⚪ B", "C": "⬜ C"}


def pipeline_leads(leads: list) -> list:
    """与看板主泳道一致：不含 pass/converted，也不含人工低优池。"""
    return [
        l
        for l in leads
        if (l.get("status") or "") not in ("pass", "converted")
        and not l.get("manual_low_priority")
    ]


def _display_name(lead: dict) -> str:
    c = (lead.get("custom_name") or "").strip()
    if c:
        return c.split(" / ")[0].strip()
    return (lead.get("name") or "").split(" / ")[0].strip() or "—"


def normalize_track(lead: dict) -> str:
    tt = (lead.get("talent_track") or "").strip()
    if not tt or tt == "general":
        return "harness_eng"
    return tt


def effective_tier(lead: dict) -> str:
    if lead.get("status") == "pass":
        return "C"
    t = lead.get("tier", "C")
    return t if t in TIER_BADGE else "C"


def group_by_track(leads: list) -> Dict[str, list]:
    buckets: Dict[str, list] = {k: [] for k in TRACK_ORDER}
    for lead in leads:
        buckets.setdefault(normalize_track(lead), []).append(lead)
    return buckets


def _tier_counts(track_leads: list) -> Dict[str, int]:
    counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for lead in track_leads:
        t = effective_tier(lead)
        counts[t] = counts.get(t, 0) + 1
    return counts


def _lead_short_line(lead: dict) -> str:
    badge = TIER_BADGE.get(effective_tier(lead), "⬜")
    name = _display_name(lead)
    current = (lead.get("current") or "").strip()
    loc = (lead.get("location") or "").strip()
    bits = [b for b in (loc, current) if b]
    suffix = f" · {' · '.join(bits[:2])}" if bits else ""
    star = " ⭐" if lead.get("priority") else ""
    return f"`{badge}` **{name}**{star}{suffix}"


def _top_sa(leads: list, limit: int = 5) -> list:
    order = {"S": 0, "A": 1, "B": 2, "C": 3}

    def sort_key(lead):
        return (
            order.get(effective_tier(lead), 9),
            -(int(lead.get("score") or 0)),
            lead.get("track_rank") or 999,
        )

    pool = [l for l in leads if effective_tier(l) in ("S", "A")]
    return sorted(pool, key=sort_key)[:limit]


def build_track_card_section(
    track_leads: list,
    track_key: str,
    *,
    today: Optional[str] = None,
    spotlight_limit: int = 5,
) -> str:
    """One job lane for Feishu card / text report."""
    today = today or date.today().isoformat()
    meta = TRACK_META[track_key]
    counts = _tier_counts(track_leads)
    spotlight = _top_sa(track_leads, spotlight_limit)
    starred = [l for l in track_leads if l.get("priority")]

    lines = [
        f"**{meta['label']}** · {len(track_leads)} 人（S{counts['S']} / A{counts['A']} / B{counts['B']}）",
    ]
    if spotlight:
        lines.append("S/A 关注：")
        for lead in spotlight:
            lines.append(f"  · {_lead_short_line(lead)}")
    else:
        lines.append("S/A 关注：_暂无_")

    if starred:
        lines.append(f"标星（{len(starred)}）：" + "、".join(_display_name(l) for l in starred[:5]))
        if len(starred) > 5:
            lines.append(f"  _…另有 {len(starred) - 5} 人，看板「仅优先」_")

    # 顶部已有「今日新增 · 按岗位」，此处不再重复「今日新增：无」占屏

    return "\n".join(lines)


def build_tracks_daily_section(
    leads: list,
    today: Optional[str] = None,
    *,
    spotlight_limit: int = 5,
) -> str:
    today = today or date.today().isoformat()
    by_track = group_by_track(pipeline_leads(leads))
    blocks = []
    for key in TRACK_ORDER:
        pool = by_track.get(key, [])
        if not pool and key == "fde":
            blocks.append(f"**{TRACK_META[key]['label']}** · 0 人")
            continue
        blocks.append(
            build_track_card_section(
                pool, key, today=today, spotlight_limit=spotlight_limit
            )
        )
    return "\n\n".join(blocks)


def build_new_leads_by_track(leads: list, today: Optional[str] = None) -> str:
    today = today or date.today().isoformat()
    new_leads = [l for l in leads if l.get("date_found") == today]
    if not new_leads:
        return "_今日无新增_"
    by_track = group_by_track(new_leads)
    parts = []
    for key in TRACK_ORDER:
        pool = by_track.get(key, [])
        if not pool:
            continue
        meta = TRACK_META[key]
        lines = [f"**{meta['short']}**（{len(pool)}）"]
        lines.extend(f"  · {_lead_short_line(l)}" for l in pool)
        parts.append("\n".join(lines))
    return "\n\n".join(parts) if parts else "_今日无新增_"


def build_track_overview_line(leads: list) -> str:
    by_track = group_by_track(pipeline_leads(leads))
    parts = []
    for key in TRACK_ORDER:
        meta = TRACK_META[key]
        n = len(by_track.get(key, []))
        c = _tier_counts(by_track.get(key, []))
        parts.append(f"{meta['short']} {n}（S{c['S']}/A{c['A']}）")
    return " · ".join(parts)


def build_daily_report_markdown(leads: list, today: Optional[str] = None) -> str:
    today = today or date.today().isoformat()
    new_count = sum(1 for l in leads if l.get("date_found") == today)
    active = pipeline_leads(leads)
    return "\n".join(
        [
            f"🆕 **今日新增**（{new_count} 人，按岗位）",
            build_new_leads_by_track(leads, today),
            "",
            f"📈 **主池** {len(active)} 人（不含不合适/已转化）· {build_track_overview_line(leads)}",
            "",
            build_tracks_daily_section(leads, today),
        ]
    )


# Backward-compatible alias
def build_fde_daily_section(leads: list, today: Optional[str] = None) -> str:
    return build_tracks_daily_section(leads, today)


def build_priority_section(leads: list, *, limit: int = 8) -> str:
    """Deprecated: priority is shown per-track in build_track_card_section."""
    starred = [l for l in leads if l.get("priority")]
    if not starred:
        return ""
    lines = [f"⭐ **标星优先**（{len(starred)} 人，详见各岗位块）"]
    for lead in sorted(
        starred,
        key=lambda l: (
            TRACK_ORDER.index(normalize_track(l))
            if normalize_track(l) in TRACK_ORDER
            else 9,
            {"S": 0, "A": 1, "B": 2, "C": 3}.get(effective_tier(l), 9),
        ),
    )[:limit]:
        meta = TRACK_META.get(normalize_track(lead), {})
        lines.append(f"  · {_lead_short_line(lead)} · {meta.get('short', '')}")
    return "\n".join(lines)
