#!/usr/bin/env python3
"""
Telos 人才库 — 飞书日报推送（GitHub Actions 版 · 自定义机器人 Webhook）

架构说明：
  sandbox 的 egress 代理屏蔽了 open.feishu.cn，所以卡片推送不能在调度任务
  沙箱里直接发，而是由 GitHub Actions (feishu-notify.yml) 在 Daily update 提交
  推上来后触发，从 GitHub 侧调用 Feishu 自定义机器人 webhook。

所需环境变量（从 GitHub Actions Secrets 注入）：
  FEISHU_WEBHOOK_URL       — 群机器人 webhook URL，形如
                             https://open.feishu.cn/open-apis/bot/v2/hook/<uuid>
  FEISHU_WEBHOOK_SECRET    — 机器人"签名校验"开启后的 secret（可选但强烈建议）

  FEISHU_WEBHOOK_URL_2     — 第二个群（可选）
  FEISHU_WEBHOOK_SECRET_2  — 第二个群的签名 secret（可选）
  FEISHU_WEBHOOK_URL_3 / _SECRET_3 ... 同理，按需加。

  额外控制：
  FEISHU_DRY_RUN=1         — 只打印目标 webhook 列表，不实际发送（本地干跑）
"""
import json, os, sys, time, hmac, hashlib, base64, datetime
import urllib.request, urllib.error

LEADS_FILE = "leads.json"
PAGES_URL  = "https://fyonyourside.github.io/telos-talent/dashboard.html"


def gen_sign(timestamp: str, secret: str) -> str:
    """飞书自定义机器人签名：HMAC-SHA256(secret, "<timestamp>\n<secret>") 再 base64。

    注意 string_to_sign 的格式是 f"{timestamp}\n{secret}"，
    然后把它整个作为 HMAC 的 key（没错，是 key 不是 message），message 为空串。
    """
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def build_card(leads_data):
    """组装 interactive 卡片 JSON。

    结构：
      header（标题，有新增时蓝色，否则灰色）
      ├─ 今日新增清单（带 tier 徽标）
      ├─ 分隔线
      ├─ 六宫格统计（总量 / S / A / B / C / 合伙人 / 优先）
      ├─ 分隔线
      ├─ S 级候选人名单
      └─ 主 CTA 按钮（打开看板）
    """
    leads = leads_data.get("leads", [])
    today = datetime.date.today().isoformat()

    new_leads = [l for l in leads if l.get("date_found") == today]
    tiers = {"S": [], "A": [], "B": [], "C": []}
    for l in leads:
        t = l.get("tier", "C")
        if t in tiers:
            tiers[t].append(l)

    partner_count  = sum(1 for l in leads if l.get("partner_potential"))
    priority_count = sum(1 for l in leads if l.get("priority"))

    # 今日新增模块
    if new_leads:
        TIER_BADGE = {"S": "🏆 S", "A": "🔵 A", "B": "⚪ B", "C": "⬜ C"}
        new_lines = []
        for l in new_leads:
            badge = TIER_BADGE.get(l.get("tier", "C"), "⬜")
            current = l.get("current", "") or ""
            loc = l.get("location", "") or ""
            suffix = f"（{loc} · {current}）" if current or loc else ""
            new_lines.append(f"`{badge}` **{l['name']}** {suffix}")
        new_section = "\n".join(new_lines)
        header_color = "blue"
    else:
        new_section = "_今日无新增_"
        header_color = "grey"

    s_names = "、".join(l["name"] for l in tiers["S"][:5]) or "无"

    total = len(leads)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_color,
            "title": {
                "tag": "plain_text",
                "content": f"📊 Telos 人才库日报 · {today}"
            }
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"🆕 **今日新增（{len(new_leads)} 人）**\n\n{new_section}"
                }
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**📈 总库存**\n{total} 人"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**🤝 合伙人候选**\n{partner_count} 人"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**🏆 S 级**\n{len(tiers['S'])} 人"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**🔵 A 级**\n{len(tiers['A'])} 人"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**⚪ B 级**\n{len(tiers['B'])} 人"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                        "content": f"**⭐ 优先跟进**\n{priority_count} 人"}}
                ]
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⭐ **S 级候选人（前 5）**：{s_names}"
                }
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 打开在线看板"},
                        "type": "primary",
                        "url": PAGES_URL
                    }
                ]
            }
        ]
    }
    return card


def post_webhook(url: str, secret: str, card: dict):
    payload = {
        "msg_type": "interactive",
        "card": card,
    }
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = gen_sign(ts, secret)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {err}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from None

    # 飞书自定义机器人成功时 code == 0 （或 StatusCode == 0），失败时 code != 0
    code = resp.get("code", resp.get("StatusCode", -1))
    if code != 0:
        raise RuntimeError(f"Webhook 返回非零 code={code}: {resp}")
    print(f"✅ 飞书卡片已推送，响应: {resp}")


def collect_webhooks():
    """
    收集所有要推送的 (url, secret, label) 三元组。

    第一组从 FEISHU_WEBHOOK_URL / FEISHU_WEBHOOK_SECRET 读（保持向后兼容）；
    后续从 FEISHU_WEBHOOK_URL_2 / _SECRET_2、_3 / _SECRET_3 ... 依次读，
    遇到没设的就停。空 URL 跳过；secret 可空（=不开签名校验）。
    """
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
        print("❌ 没有任何 FEISHU_WEBHOOK_URL[_N] 环境变量；"
              "请在 GitHub repo Settings → Secrets and variables → Actions 中配置")
        sys.exit(1)

    dry_run = os.environ.get("FEISHU_DRY_RUN", "").strip() in ("1", "true", "yes")

    with open(LEADS_FILE, encoding="utf-8") as f:
        leads_data = json.load(f)

    card = build_card(leads_data)
    print("--- 卡片内容预览 ---")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print("---")
    print(f"📡 推送目标数：{len(targets)}")
    for _, _, label in targets:
        print(f"   • {label}")

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

    # 部分失败：打印汇总；只有全部失败才退出非 0
    if failures:
        print(f"⚠️  {len(failures)}/{len(targets)} 个群推送失败")
        for label, err in failures:
            print(f"   - {label}: {err}")
        if len(failures) == len(targets):
            sys.exit(1)


if __name__ == "__main__":
    main()
