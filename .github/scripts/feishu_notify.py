#!/usr/bin/env python3
"""
Telos 人才库 — 飞书日报推送（GitHub Actions 版 · 自定义机器人 Webhook）

卡片结构：仅按四岗位（Harness / Research / PM / FDE）分块，与看板泳道一致。
不含已废弃的维度筛选、合伙人候选等分类。
"""
import json, os, sys, time, hmac, hashlib, base64, datetime
import urllib.request, urllib.error
from pathlib import Path

LEADS_FILE = "leads.json"
PAGES_URL  = "https://fyonyourside.github.io/telos-talent/dashboard.html"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.report_sections import (
    TRACK_META,
    TRACK_ORDER,
    build_new_leads_by_track,
    build_track_card_section,
    build_track_overview_line,
    group_by_track,
    pipeline_leads,
)


def gen_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def build_card(leads_data):
    leads = leads_data.get("leads", [])
    active = pipeline_leads(leads)
    today = datetime.date.today().isoformat()
    new_count = sum(1 for l in leads if l.get("date_found") == today)
    header_color = "blue" if new_count else "grey"
    by_track = group_by_track(active)

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**今日新增（{new_count} 人）** · 按岗位\n\n"
                    f"{build_new_leads_by_track(leads, today)}\n\n"
                    f"📈 **主池 {len(active)} 人**（不含不合适/已转化）· {build_track_overview_line(leads)}"
                ),
            },
        },
        {"tag": "hr"},
    ]

    for key in TRACK_ORDER:
        meta = TRACK_META[key]
        pool = by_track.get(key, [])
        body = build_track_card_section(pool, key, today=today, spotlight_limit=5)
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": body},
        })
        elements.append({"tag": "hr"})

    # Remove trailing hr
    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📋 打开四列看板"},
                "type": "primary",
                "url": PAGES_URL,
            }
        ],
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_color,
            "title": {
                "tag": "plain_text",
                "content": f"📊 Telos 人才库 · 岗位日报 · {today}",
            },
        },
        "elements": elements,
    }
    return card


def post_webhook(url: str, secret: str, card: dict):
    payload = {"msg_type": "interactive", "card": card}
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = gen_sign(ts, secret)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {err}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from None

    code = resp.get("code", resp.get("StatusCode", -1))
    if code != 0:
        raise RuntimeError(f"Webhook 返回非零 code={code}: {resp}")
    print(f"✅ 飞书卡片已推送，响应: {resp}")


def collect_webhooks():
    targets = []
    url1 = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    sec1 = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    if url1:
        targets.append((url1, sec1, "群1"))
    i = 2
    while True:
        url = os.environ.get(f"FEISHU_WEBHOOK_URL_{i}", "").strip()
        sec = os.environ.get(f"FEISHU_WEBHOOK_SECRET_{i}", "").strip()
        if not url:
            break
        targets.append((url, sec, f"群{i}"))
        i += 1
    return targets


def main():
    targets = collect_webhooks()
    if not targets:
        print("❌ 没有任何 FEISHU_WEBHOOK_URL[_N] 环境变量")
        sys.exit(1)

    dry_run = os.environ.get("FEISHU_DRY_RUN", "").strip() in ("1", "true", "yes")
    with open(LEADS_FILE, encoding="utf-8") as f:
        leads_data = json.load(f)

    card = build_card(leads_data)
    print("--- 卡片内容预览 ---")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print("---")

    if dry_run:
        print("🧪 DRY RUN — 跳过实际推送")
        return

    failures = []
    for url, secret, label in targets:
        try:
            print(f"→ 推送 {label} ...")
            post_webhook(url, secret, card)
        except Exception as e:
            print(f"⚠️  {label} 推送失败：{e}")
            failures.append((label, str(e)))

    if failures and len(failures) == len(targets):
        sys.exit(1)


if __name__ == "__main__":
    main()
