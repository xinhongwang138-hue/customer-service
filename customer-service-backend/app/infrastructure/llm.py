# infrastructure/llm.py ｜ 基础设施层：把各家大模型统一为 BaseChatModel 客户端
# 被谁调用：Engine 引擎做推理时复用本模块的全局单例 llm
# 要点：换厂商只改 settings 配置，业务与推理代码一行都不用动
# 补充：未配置 LLM_API_KEY 时自动降级为「本地规则模型」，
#         不用任何密钥也能把三条轨道（任务/知识/闲聊）完整跑通，方便离线演示与调试。

# app/infrastructure/llm.py

# json：本地规则模型要拼 TurnPlan 的 JSON 字符串
import json
# logging：降级时打一条提示，方便知道当前走的是真实模型还是规则模型
import logging
# re：从提示词里切分段落、识别订单号
import re
# 类型标注
from typing import Any, List

# init_chat_model 是 LangChain 提供的"一行初始化任意厂商模型"入口
from langchain.chat_models import init_chat_model
# BaseChatModel 是所有聊天模型共有的抽象基类，即统一的"鸭子类型"
from langchain_core.language_models import BaseChatModel
# 消息与返回结构：自建模型也要吐标准的 AIMessage / ChatResult
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

# 模型名、密钥、网关等配置统一从 conf.settings 读取
from conf.config import settings

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# 一、本地规则模型：没有 LLM 密钥时的兜底实现
# ════════════════════════════════════════════════════════════════════════════
# 它实现的是同一个 BaseChatModel 接口，所以 planner / responder 完全无感，
# 上层一行代码都不用改——这就是"面向接口编程"的好处。


def _flatten(messages: List[BaseMessage]) -> str:
    """把消息列表压成一段纯文本，规则匹配只需要文本。"""
    parts = []
    for m in messages:
        content = m.content
        # 多模态消息的 content 可能是 list[dict]，这里只取文本片段
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        parts.append(str(content))
    return "\n".join(parts)


def _section(text: str, start: str, end: str) -> str:
    """截取 start 标记之后、end 标记之前的内容；找不到就返回空串。"""
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i:] .strip() if j < 0 else text[i:j].strip()


def _loads(raw: str) -> Any:
    """容错 JSON 解析：允许前后夹带说明文字，取第一个完整的 { } / [ ] 块。"""
    if not raw:
        return None
    raw = raw.strip()
    if raw in ("null", "None", ""):
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    # 退化路径：从第一个 { 或 [ 到最后一个配对符号
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        i = raw.find(open_ch)
        j = raw.rfind(close_ch)
        if 0 <= i < j:
            try:
                return json.loads(raw[i:j + 1])
            except Exception:
                continue
    return None


# 步骤 → 正在收集的槽位名（与 flow_config 里的 step id 对应）
_STEP_SLOT = {
    "ask_order_number": "order_number",
    "ask_refund_reason": "refund_reason",
    "ask_product_id": "product_id",
}

# 政策/知识类关键词 → 知识意图 id（必须先于业务动作判断，否则"退款政策"会误启退款流程）
_INTENT_RULES = [
    (("退款政策", "退款多久", "多久到账", "几天到账", "退款规则", "退款流程是怎样的"), "refund_policy"),
    (("退货", "七天无理由", "无理由", "退换"), "return_policy"),
    (("发货", "配送", "包邮", "运费", "多久能到", "什么时候发"), "shipping_policy"),
    (("平台规则", "有什么限制", "违规"), "platform_rule"),
    (("优惠券", "怎么领", "活动", "满减"), "general_ecommerce_info"),
]

# 业务动作关键词 → 流程 id
_FLOW_RULES = [
    (("转人工", "人工客服", "真人", "客服电话"), "human_handoff"),
    (("物流", "快递", "到哪了", "运到", "签收"), "logistics_tracking"),
    (("退款", "退钱"), "refund_request"),
    (("推荐", "相似", "类似", "同款", "别的款"), "similar_product_recommendation"),
    (("订单状态", "查订单", "订单怎么样", "订单到", "我的订单", "查一下订单"), "order_status_query"),
]

# 常见寒暄
_GREETING = ("你好", "您好", "hi", "hello", "哈喽", "在吗", "在么")


def _match_flow(msg: str, flow_ids: set[str]) -> str | None:
    """按关键词匹配业务流程；flow_ids 用于过滤当前 YAML 里真实存在的流程。"""
    for words, flow_id in _FLOW_RULES:
        if flow_id not in flow_ids:
            continue
        if any(w in msg for w in words):
            return flow_id
    return None


def _match_intent(msg: str) -> str | None:
    for words, intent in _INTENT_RULES:
        if any(w in msg for w in words):
            return intent
    return None


def _extract_slot_value(msg: str, slot: str) -> str | None:
    """从用户这句话里抽取槽位值；抽不到就返回 None（宁可再问一遍也不瞎填）。"""
    if slot in ("order_number", "product_id"):
        m = re.search(r"[A-Za-z]{1,4}\d{5,}", msg)
        if m:
            return m.group(0)
        m = re.search(r"\b\d{6,}\b", msg)
        return m.group(0) if m else None
    if slot == "refund_reason":
        v = re.sub(r"^(退款)?(原因|理由)?[是为：:\s]*", "", msg).strip()
        return v or None
    return msg or None


def _plan_json(task: dict | None = None, knowledge: dict | None = None,
               chitchat: dict | None = None) -> str:
    """按 TurnPlan 的契约拼 JSON：三条轨道同时只有一个非 null。"""
    return json.dumps(
        {"task": task, "knowledge": knowledge, "chitchat": chitchat},
        ensure_ascii=False,
    )


def _offline_plan(prompt: str) -> str:
    """规则版意图规划：把用户话映射成 TurnPlan（task / knowledge / chitchat）。"""
    user_msg = _section(prompt, "## 用户最新消息", "## 历史对话")
    active = _loads(_section(prompt, "## 当前激活任务", "## 已中断（挂起）的任务"))
    paused = _loads(_section(prompt, "## 已中断（挂起）的任务", "## 用户当前聚焦的对象"))
    focused = _loads(_section(prompt, "## 用户当前聚焦的对象", "## 可用的业务流程图"))
    flows_payload = _loads(_section(prompt, "## 可用的业务流程图", "## 可用的知识意图")) or {}

    flow_ids = {f.get("id") for f in flows_payload.get("flows", []) if isinstance(f, dict)}
    msg = re.sub(r"\s+", " ", user_msg or "").strip()

    # 0) 空消息：当闲聊兜底
    if not msg:
        return _plan_json(chitchat={})

    # 1) 取消当前任务（"算了/不办了"）
    if isinstance(active, dict) and re.search(r"(算了|取消|不办了|不要了|先不|别弄了|退出)", msg):
        return _plan_json(task={"commands": [{"command": "cancel_flow"}]})

    # 2) 恢复挂起的任务（"继续刚才那个退款"）
    #    必须排在"活跃任务补槽"之前：否则这句话里的"退款"会被当成"切换到新流程"，
    #    用户想恢复旧任务，结果旧任务又被挂起一次。
    if isinstance(paused, list) and paused and re.search(r"(继续|接着|刚才那个|回到|还是)", msg):
        hinted = _match_flow(msg, flow_ids)
        target = None
        # 先按消息里提到的业务名在挂起栈里精确找
        if hinted:
            target = next(
                (p for p in paused if isinstance(p, dict) and p.get("flow_id") == hinted), None
            )
        # 找不到就用栈顶（最近被挂起的那个）
        target = target or next(
            (p for p in paused if isinstance(p, dict) and p.get("flow_id")), None
        )
        if target:
            return _plan_json(task={"commands": [
                {"command": "resume_flow", "flow": target["flow_id"]}
            ]})

    # 3) 正在办业务：优先当成"补充槽位"
    if isinstance(active, dict):
        cur_flow = active.get("flow_id")
        step_id = active.get("step_id") or ""
        new_flow = _match_flow(msg, flow_ids)

        # 用户明确点了另一条业务 → 切换流程（旧流程由 CommandProcessor 挂起）
        if new_flow and new_flow != cur_flow:
            return _plan_json(task={"commands": [{"command": "start_flow", "flow": new_flow}]})

        # 仍在本流程：按当前 collect 步骤抽槽位值
        slot_name = _STEP_SLOT.get(step_id)
        if slot_name:
            value = _extract_slot_value(msg, slot_name)
            if value:
                return _plan_json(task={"commands": [
                    {"command": "set_slots", "slots": {slot_name: value}}
                ]})

        # 已经答非所问：交给澄清（空计划 → missing_task_commands）
        return _plan_json()

    # 3) 政策/知识类咨询优先（避免"退款政策"误触发退款流程）
    intent = _match_intent(msg)
    if intent:
        return _plan_json(knowledge={"intents": [intent]})

    # 4) 带着聚焦对象问它的情况 → 商品/订单信息咨询
    if isinstance(focused, dict) and focused.get("type") in ("product", "order"):
        if re.search(r"(多少钱|价格|什么材质|怎么样|详情|有货|库存|状态|到哪|什么情况|这个|它|呢)", msg):
            target = "product_info" if focused.get("type") == "product" else "order_info"
            return _plan_json(knowledge={"intents": [target]})

    # 5) 业务动作
    flow = _match_flow(msg, flow_ids)
    if flow:
        commands: list[dict] = [{"command": "start_flow", "flow": flow}]
        # 用户已经点过卡片：顺手把订单号/商品号填进槽位，省掉一轮"请告诉我订单号"
        if isinstance(focused, dict) and focused.get("id"):
            if focused.get("type") == "order" and flow in (
                "order_status_query", "logistics_tracking", "refund_request"
            ):
                commands.append({"command": "set_slots", "slots": {"order_number": focused["id"]}})
            elif focused.get("type") == "product" and flow == "similar_product_recommendation":
                commands.append({"command": "set_slots", "slots": {"product_id": focused["id"]}})
        return _plan_json(task={"commands": commands})

    # 6) 寒暄与兜底
    return _plan_json(chitchat={})


def _money(value: Any) -> str:
    """金额美化：129.0 → ¥129，129.5 → ¥129.5。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"¥{num:.0f}" if abs(num - round(num)) < 1e-9 else f"¥{num:.2f}"


def _fmt_product_chunk(payload: dict) -> str:
    """把商品 JSON 说成人话（离线模式没有 LLM 帮忙润色）。"""
    name = payload.get("name") or "该商品"
    price = payload.get("price")
    stock = payload.get("stock_status") or payload.get("stock")
    desc = payload.get("description") or ""
    parts = [f"这件商品是「{name}」"]
    if price is not None:
        parts.append(f"当前价格 {_money(price)}")
    if stock is not None:
        parts.append(f"库存状态：{stock}")
    text = "，".join(parts) + "。"
    if desc:
        text += f"{desc}"
    return text


def _fmt_order_chunk(payload: dict) -> str:
    """把"订单 + 物流"JSON 说成人话。"""
    order = payload.get("order") or {}
    logistics = payload.get("logistics") or {}
    num = payload.get("order_number") or order.get("order_number") or ""
    lines = [f"订单 {num} 当前状态是：{order.get('status_desc') or order.get('status') or '未知'}"]
    if order.get("amount"):
        lines.append(f"订单金额 {_money(order['amount'])}")
    items = order.get("items") or []
    titles = [str(i.get("title_snapshot") or "").strip() for i in items[:3] if i.get("title_snapshot")]
    if titles:
        lines.append("商品：" + "、".join(titles))
    if logistics:
        company = logistics.get("logistics_company") or "快递"
        tracking = logistics.get("tracking_number") or ""
        status = logistics.get("status_desc") or logistics.get("status") or ""
        seg = f"物流由{company}配送"
        if tracking:
            seg += f"，单号 {tracking}"
        if status:
            seg += f"，当前{status}"
        lines.append(seg)
    return "。".join(lines) + "。"


def _offline_knowledge(prompt: str) -> str:
    """规则版知识作答：有结构化数据就格式化，没有就诚实说没查到。"""
    body = _section(prompt, "以下是与用户问题相关的商品或业务信息，请优先基于这些内容作答：", "要求：")

    # 1) 商品信息（注意 providers 里用的是半角冒号）
    if "商品信息" in body:
        payload = _loads(body.split("商品信息", 1)[1])
        if isinstance(payload, dict):
            return _fmt_product_chunk(payload)

    # 2) 订单 + 物流（providers 里用的是全角冒号，所以这里不带冒号匹配）
    if "订单与物流信息" in body:
        payload = _loads(body.split("订单与物流信息", 1)[1])
        if isinstance(payload, dict):
            return _fmt_order_chunk(payload)

    # 3) FAQ 标准问答优先（最贴用户问题，且措辞本身就是成稿）
    m = re.search(r"FAQ[：:]\s*(.+?)(?=\n\s*RAG[：:·]|\Z)", body, re.S)
    if m:
        ans = re.sub(r"\s*\n\s*", "", m.group(1)).strip()
        if ans and "未检索到" not in ans:
            return ans[:400]

    # 4) RAG 文档片段（比 FAQ 长，取正文即可）
    m = re.search(r"RAG[·:：]\s*(.+?)(?=\n\s*(?:FAQ|RAG)[：:·]|\Z)", body, re.S)
    if m:
        ans = re.sub(r"\s*\n\s*", "", m.group(1)).strip()
        if ans and "未检索到" not in ans:
            return ans[:400]

    return "这个问题我暂时没有查到确切的信息。你可以再补充一下具体情况，我帮你进一步确认。"


def _offline_clarify(prompt: str) -> str:
    """规则版澄清：直接用系统给的基础话术，不做润色（本来规则话术就是人话）。"""
    text = _section(prompt, "建议回复：", "当前聚焦对象")
    if not text:
        text = _section(prompt, "建议回复：", "对话历史")
    if not text:
        i = prompt.find("建议回复：")
        text = prompt[i + len("建议回复："):] if i >= 0 else ""
    text = text.strip().split("\n")[0].strip()
    return text or "抱歉，我没太理解你的意思，可以再具体说一下吗？"


def _offline_chitchat(prompt: str) -> str:
    """规则版闲聊：按关键词给一句自然的回应。"""
    user_msg = _section(prompt, "用户最后一句：", "你的回复：") or prompt
    msg = user_msg.strip()

    if any(g in msg for g in ("谢谢", "感谢", "多谢")):
        return "不客气～还有订单、物流或商品的问题，随时找我。"
    if any(g in msg for g in ("再见", "拜拜", "没事了")):
        return "好的，祝你购物愉快，有问题随时回来找我。"
    if any(g in msg for g in _GREETING):
        return "你好，这里是电商小二。我可以帮你查订单状态、查物流、了解商品信息，或者提交退款申请。"
    if any(g in msg for g in ("聪明", "厉害", "棒")):
        return "谢谢夸奖。如果你有订单、物流或者商品相关的问题，我都可以继续帮你看一下。"
    if any(g in msg for g in ("你是谁", "你叫什么", "介绍")):
        return "我是电商小二，可以帮你查订单、查物流、看商品信息，也能帮你提交退款申请。"
    return "我在的。你可以直接说想办的业务，比如「查一下我的订单」「我的快递到哪了」，我会一步步帮你处理。"


class OfflineChatModel(BaseChatModel):
    """本地规则模型：实现 BaseChatModel 接口，零密钥可用。

    它的判断依据是"提示词长什么样"——不同模板有各自的标题特征，
    据此分派到 规划 / 知识作答 / 澄清 / 闲聊 四种规则处理器。
    """

    @property
    def _llm_type(self) -> str:
        return "offline-rule"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: List[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = _flatten(messages)

        # 按模板特征分派（特征串取自 prompts/jinja2 下的各模板标题）
        if "## 可用的业务流程图" in prompt:
            output = _offline_plan(prompt)          # 意图规划 → 必须输出 JSON
        elif "澄清原因：" in prompt and "建议回复：" in prompt:
            output = _offline_clarify(prompt)       # 澄清润色 → 输出一句追问
        elif "助手回复：" in prompt:
            output = _offline_knowledge(prompt)     # 知识作答 → 基于检索结果说话
        elif "你的回复：" in prompt:
            output = _offline_chitchat(prompt)      # 闲聊 → 一句自然回应
        else:
            output = "好的，我可以帮你查订单、查物流、看商品信息，也能帮你提交退款申请。"

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=output))])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: List[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        # 规则计算是纯 CPU 的，没有 IO，直接复用同步实现
        return self._generate(messages, stop, run_manager, **kwargs)


# ════════════════════════════════════════════════════════════════════════════
# 二、单例出口：有密钥用真模型，没密钥用规则模型
# ════════════════════════════════════════════════════════════════════════════


def _build_llm() -> BaseChatModel:
    api_key = (settings.llm_api_key or "").strip()
    # 常见占位符也视同"没配"
    if api_key and api_key.lower() not in ("sk-xxx", "your-api-key", "none", "null"):
        logger.info("LLM 已接入：%s @ %s", settings.llm_model, settings.llm_base_url)
        return init_chat_model(
            model=settings.llm_model,
            model_provider="openai",
            api_key=api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )
    logger.warning(
        "未配置 LLM_API_KEY，已启用本地规则模型（离线可跑，但回答质量弱于真实大模型）。"
        "在 .env 里填入 key 即可自动切换。"
    )
    return OfflineChatModel()


# 模块级单例：文件被 import 即创建好 llm，全项目共享同一客户端
llm: BaseChatModel = _build_llm()


# 直接运行本文件即自测连通性；被 import 时这段不执行
if __name__ == '__main__':
    # invoke 是同步调用；.content 取出模型回复的文本
    print(llm.invoke("你好").content)
