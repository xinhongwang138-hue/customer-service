#!/usr/bin/env python
# ══════════════════════════════════════════════════════════════════════════
# 端到端冒烟测试：真实 HTTP 调用，不使用任何 mock
# 用法：先 python start.py 起服务，再 python smoke_test.py
# ══════════════════════════════════════════════════════════════════════════
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

CHAT = "http://127.0.0.1:18082"
COMMERCE = "http://127.0.0.1:18081"

# 这些域名必须绕过系统代理，否则本机回环请求会被代理劫持
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_passed = 0
_failed = 0


def http(url: str, payload: dict | None = None, timeout: int = 30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"} if data else {}
    )
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat(sender: str, text: str | None = None, obj: dict | None = None) -> str:
    """发一条消息，把机器人所有回复拼成一段文本。"""
    payload = {"sender_id": sender}
    if text:
        payload["text"] = text
    if obj:
        payload["object"] = obj
    result = http(f"{CHAT}/api/chat", payload)
    return "\n".join(m.get("text") or "" for m in result.get("messages", []))


def new_user(prefix: str = "t") -> str:
    """每次用新用户，避免上一轮遗留状态干扰。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}   {detail}")


def section(title: str) -> None:
    print(f"\n{title}")


def main() -> int:
    print("=" * 62)
    print("  电商小二 · 端到端冒烟测试")
    print("=" * 62)

    # ── 0. 服务健康 ────────────────────────────────────────────────────
    section("[0] 服务连通")
    try:
        h = http(f"{COMMERCE}/health")
        check("模拟电商中台 /health", h.get("code") == 0, str(h))
    except Exception as e:
        check("模拟电商中台 /health", False, repr(e))
        print("\n中台没起来，先执行 python start.py")
        return 1

    try:
        meta = http(f"{CHAT}/api/meta")
        mode = "本地规则引擎" if meta.get("offline") else meta.get("llm")
        check(f"客服后端 /api/meta（当前：{mode}）", "llm" in meta, str(meta))
    except Exception as e:
        check("客服后端 /api/meta", False, repr(e))
        return 1

    # ── 1. 中台接口 ────────────────────────────────────────────────────
    section("[1] 中台数据接口")
    orders = http(f"{COMMERCE}/users/u1001/orders")
    check("用户订单列表", len(orders.get("data") or []) >= 2, str(orders)[:120])

    order = http(f"{COMMERCE}/orders/A20240315001")
    d = order.get("data") or {}
    check("订单详情字段完整", d.get("status_desc") == "已发货" and d.get("amount") == 129.0, str(d)[:120])

    logi = http(f"{COMMERCE}/orders/A20240315001/logistics")
    ld = logi.get("data") or {}
    check("物流轨迹", ld.get("tracking_number") == "SF1234567890" and len(ld.get("traces") or []) >= 3, str(ld)[:120])

    prod = http(f"{COMMERCE}/products/P1001")
    pd = prod.get("data") or {}
    check("商品详情", pd.get("name") == "轻薄连帽防晒衣" and pd.get("price") == 129.0, str(pd)[:120])

    missing = http(f"{COMMERCE}/orders/NOT_EXIST")
    check("不存在的订单返回 code=404", missing.get("code") == 404 and missing.get("data") is None, str(missing))

    # ── 2. 闲聊 ────────────────────────────────────────────────────────
    section("[2] 闲聊轨道")
    reply = chat(new_user("chat"), "你好")
    check("打招呼有回应", "电商小二" in reply or "助手" in reply, reply[:80])

    # ── 3. 任务流程 ────────────────────────────────────────────────────
    section("[3] 任务流程轨道")
    u = new_user("order")
    r1 = chat(u, "帮我查下订单状态")
    check("开流程并追问订单号", "订单号" in r1, r1[:80])
    r2 = chat(u, "A20240315001")
    check("查订单结果含状态与金额", "已发货" in r2 and "129" in r2, r2[:120])

    u = new_user("logi")
    chat(u, "我的快递到哪了")
    r = chat(u, "A20240315001")
    check("查物流结果含承运商与单号", "顺丰" in r and "SF1234567890" in r, r[:120])

    u = new_user("refund")
    chat(u, "我要退款")
    r = chat(u, "A20240315001")
    check("退款第二步问原因", "原因" in r, r[:80])
    r = chat(u, "尺码不合适")
    check("退款提交成功", "已提交" in r and "尺码不合适" in r, r[:120])

    u = new_user("handoff")
    r = chat(u, "我要转人工")
    check("转人工", "人工客服" in r, r[:80])

    # ── 4. 对象消息 ────────────────────────────────────────────────────
    section("[4] 对象消息（点卡片）")
    u = new_user("obj")
    r = chat(u, obj={"type": "order", "id": "A20240315001", "title": "轻薄连帽防晒衣"})
    check("收订单卡片有引导", "收到" in r or "订单" in r, r[:80])
    r = chat(u, "我要退款")
    check("点卡片后退款跳过订单号追问", "原因" in r and "订单号" not in r, r[:120])

    u = new_user("objprod")
    chat(u, obj={"type": "product", "id": "P1001", "title": "轻薄连帽防晒衣"})
    r = chat(u, "这个多少钱，有货吗")
    check("商品咨询返回价格与库存", "129" in r and "有货" in r, r[:120])

    u = new_user("rec")
    chat(u, obj={"type": "product", "id": "P1001", "title": "轻薄连帽防晒衣"})
    r = chat(u, "推荐相似商品")
    check("相似商品有真实召回", "纯棉基础T恤" in r or "牛仔裤" in r, r[:160])

    # ── 5. 知识轨道 ────────────────────────────────────────────────────
    section("[5] 知识检索轨道")
    r = chat(new_user("faq1"), "退款多久能到账")
    check("退款时效 FAQ", "工作日" in r, r[:120])
    r = chat(new_user("faq2"), "支持七天无理由吗")
    check("退货政策 FAQ", "7" in r and "签收" in r, r[:120])
    r = chat(new_user("faq3"), "多久发货")
    check("配送时效 FAQ", "48" in r or "发货" in r, r[:120])
    r = chat(new_user("faq4"), "包邮吗")
    check("运费政策 FAQ", "99" in r or "运费" in r, r[:120])

    # ── 6. 流程控制 ────────────────────────────────────────────────────
    section("[6] 流程控制")
    u = new_user("cancel")
    chat(u, "我要退款")
    r = chat(u, "算了不退了")
    check("取消流程", "取消" in r, r[:80])

    u = new_user("resume")
    chat(u, "我要退款")
    chat(u, "我的快递到哪了")
    r = chat(u, "继续刚才那个退款")
    check("恢复挂起任务话术正确", "继续" in r and "退款" in r, r[:120])
    r = chat(u, "A20240315001")
    check("恢复后流程可继续", "原因" in r, r[:80])

    # ── 7. 历史 ────────────────────────────────────────────────────────
    section("[7] 历史记录")
    u = new_user("hist")
    chat(u, "你好")
    hist = http(f"{CHAT}/api/chat/history?sender_id={u}")
    msgs = hist.get("messages") or []
    check("历史含 user 与 bot 两条", len(msgs) >= 2 and {m["role"] for m in msgs} == {"user", "bot"}, str(msgs)[:150])
    check("历史带 session_id", all(m.get("session_id") for m in msgs), str(msgs)[:150])

    # ── 汇总 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    total = _passed + _failed
    print(f"  结果：{_passed}/{total} 通过" + (f"，{_failed} 项失败" if _failed else "，全部通过"))
    print("=" * 62)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
