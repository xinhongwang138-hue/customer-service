# service/dialogue_service.py ｜ Service 层：对话业务的"总编排者"，不含底层细节
# 被谁调用：API 路由层（chat_router，依赖由 dependencies 组装）；它再向下调仓储与引擎
# 依赖方向：上层只依赖下层接口（Repository/Engine），下层不反向依赖，形成单向分层

# app/service/dialogue_service.py

# 入参 UserMessage、出参 ProcessResult 都是 domain 层的 pydantic 模型
from domain.messages import UserMessage, ProcessResult
# DialogueState 是跨层传递的"对话状态"领域对象
from domain.state import DialogueState
# Repository 是下层：负责对话状态的持久化读写（load/save）
from repository.dialogue_state_repository import DialogueStateRepository
# Engine 是下层：负责调用 LLM 等核心能力做真正的对话推理
from engine.dialogue_engine import DialogueEngine
# 历史接口：响应模型 + 把领域消息渲染成接口历史消息的渲染器
from api.schemas import ChatObject, HistoryMessage
# 注：HistoryBuilder 只有 _render_user_message(msg) -> str（给提示词用的文本渲染），
# 签名与返回类型都对不上历史接口要的 HistoryMessage，直接调用必然 AttributeError，
# 故在下方由 service 层自行转换。


# Service 只做"编排"，既不写 SQL 也不直接调 LLM
class DialogueService:
    """
    处理对话的业务类
    """

    # 构造注入依赖：仓储/引擎由外部组装好后传入，便于替换与单元测试
    def __init__(self, dialogue_state_repository: DialogueStateRepository,
                 dialogue_engine: DialogueEngine):
        # 把仓储引用存为实例属性，供本类各方法随时调用
        self.dialogue_state_repository = dialogue_state_repository
        # 把引擎引用存为实例属性，推理时拿出来用
        self.dialogue_engine = dialogue_engine

    # async 定义协程：内部多处 await，IO 等待时不阻塞进程
    async def process_message(self, user_message: UserMessage) -> ProcessResult:
        """
        核心处理逻辑(IO：很慢/计算:调用LLM以及执行引擎、比较慢)
        :param user_message:
        :return:
        """
        # 1. 通过 repository 根据 sender_id 加载对话状态(O 阶段)
        # await 挂起等 IO 返回；老用户拿到历史状态，新用户得到空状态
        dialogue_state: DialogueState = await self.dialogue_state_repository.load_state(user_message.sender_id)
        # 2. 使用 engine 根据对话状态处理最新消息
        # 把"历史状态+新消息"交给引擎推理，LLM 较慢，await 期间可服务他人
        process_result: ProcessResult = await self.dialogue_engine.process_message(dialogue_state, user_message)
        # 3. 通过 repository 保存最新的对话状态(I 阶段)
        # 引擎已更新 dialogue_state，这里交给仓储把最新状态写回数据库
        await self.dialogue_state_repository.save_state(dialogue_state)
        # 4. 返回本轮处理结果
        # 把处理结果返回给上层 API，由它转换成 HTTP 响应
        return process_result

    # 加载历史对话给前端页面展示
    async def load_chat_history(self, sender_id: str) -> list[HistoryMessage]:
        """
        加载该用户的全部历史消息（session -> turns 展开成平铺消息列表，每条带 session_id）
        :param sender_id:
        :return:
        """
        # 1. 根据 sender_id 从数据库加载完整 DialogueState
        state: DialogueState = await self.dialogue_state_repository.load_state(sender_id)

        # 2. 遍历 state.sessions，把每个 turn 展开成消息列表
        chat_messages: list[HistoryMessage] = []
        # 外层循环:逐个会话取历史
        for session in state.sessions:
            # 内层循环:把一个会话的每个 turn 摊平
            for turn in session.turns:
                # 用户消息带所属 session_id
                chat_messages.append(
                    self._to_history_message(session.session_id, turn.user_message)
                )
                # 该轮所有机器人回复带同一个 session_id
                chat_messages.extend([
                    self._to_history_message(session.session_id, b_msg)
                    for b_msg in turn.bot_messages
                ])

        # 3. 返回给 router 组装的结果
        return chat_messages

    # 领域消息 → 接口历史消息：role 靠类型判定，对象卡片原样透传
    @staticmethod
    def _to_history_message(session_id: str, message: UserMessage | object) -> HistoryMessage:
        """
        把领域里的 UserMessage / BotMessage 转成前端要的 HistoryMessage。
        :param session_id: 该消息所属会话
        :param message: UserMessage 或 BotMessage
        """
        # 类型即角色：UserMessage 是用户，其余（BotMessage）一律当机器人
        role = "user" if isinstance(message, UserMessage) else "bot"
        obj = getattr(message, "object", None)
        return HistoryMessage(
            session_id=session_id,
            role=role,
            text=message.text,
            object=ChatObject(
                type=obj.type,
                id=obj.id,
                title=obj.title,
                attributes=obj.attributes,
            ) if obj is not None else None,
        )
