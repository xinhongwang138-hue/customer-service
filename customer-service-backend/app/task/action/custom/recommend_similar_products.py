# ═══════════════════════════════════════════════════════════════════════════
# 文件职责：RecommendSimilarProductsAction——基于当前商品推荐同类商品
# 所在层：task.action.custom（自定义动作，被 builder 自动扫描注册）
# 被谁调用：YAML 流程里 action: action_recommend_similar_products 的步骤
# ═══════════════════════════════════════════════════════════════════════════
# task/action/custom/recommend_similar_products.py

# 模块文档串：与两个 Lookup 动作相反，它直接产出 messages——因为它"自己就会说话"
"""
RecommendSimilarProductsAction：推荐相似商品
读槽位 product_id → 查当前商品 → 拉同类商品（排除自己、优先有货）→ 直接回复。
查不到商品时退化成"请先选择商品"的柔化措辞，不让流程崩。
"""

# Any：action_kwargs 的类型标注，与基类签名保持一致
from typing import Any

# BotMessage：本动作直接回复用户，产物要装 messages
from domain.messages import BotMessage
# DialogueState：从槽位表里取用户点选的商品
from domain.state import DialogueState
# 动作基类 + 产物类型
from task.action.base import Action, ActionResult
# 复用 shared 里的商品查询工具
from task.action.custom.shared import fetch_product, fetch_products


def _money(v: Any) -> str:
    """金额美化：199.0 → ¥199。"""
    try:
        num = float(v)
    except (TypeError, ValueError):
        return ""
    return f"¥{num:.0f}" if abs(num - round(num)) < 1e-9 else f"¥{num:.2f}"


# 推荐相似商品动作：同品类召回，最多 3 个
class RecommendSimilarProductsAction(Action):
    name = "action_recommend_similar_products"
    # 名字是注册表的 key，builder 扫描到本类会自动注册

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        # 当前商品：可能是用户点卡片带来的，也可能是 collect 步骤问出来的
        product_id = state.active_task.slots.get("product_id")
        current = await fetch_product(product_id) if product_id else None

        # 兜底 1：没有商品上下文 → 引导用户先选一个
        if not product_id:
            return ActionResult(messages=[BotMessage(
                text="请先在右侧选择一个商品，我再帮你找同类的好物。"
            )])

        # 兜底 2：商品查不到（接口故障或 id 不存在）
        if not current:
            return ActionResult(messages=[BotMessage(
                text=f"抱歉，我没查到商品 {product_id} 的信息，换一个商品试试？"
            )])

        name = current.get("name") or product_id
        category = current.get("category") or ""

        # 候选池：同品类、排除自己，有货的排前面
        candidates = [
            p for p in await fetch_products()
            if p.get("id") != product_id and (not category or p.get("category") == category)
        ]
        candidates.sort(key=lambda p: (0 if (p.get("stock") or 0) > 0 else 1, p.get("price") or 0))

        if not candidates:
            return ActionResult(messages=[BotMessage(
                text=f"「{name}」暂时没有找到同类商品，后续上新我再通知你。"
            )])

        lines = [f"和你正在看的「{name}」（{_money(current.get('price'))}）同类里，这几件也不错："]
        for idx, p in enumerate(candidates[:3], 1):
            stock_tag = "" if (p.get("stock") or 0) > 0 else "（暂时缺货）"
            lines.append(f"{idx}. {p.get('name')} {_money(p.get('price'))}{stock_tag}")
        lines.append("想看哪件的详情，点右侧商品卡片发给我就行。")

        return ActionResult(messages=[BotMessage(text="\n".join(lines))])
