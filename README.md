# 电商小二 · AI 电商客服

一套可运行的电商智能客服：
**FastAPI + LangChain + 三轨道对话引擎（任务流程 / 知识检索 / 闲聊）**。

三条轨道在同一轮对话里协同：要办业务的走 YAML 流程状态机，问政策的走意图检索，
剩下的话交给闲聊兜底。不是脚手架，是能真跑、能对话、能查真数据的完整实现。

仓库地址：<https://github.com/xinhongwang138-hue/customer-service>

---

## 一、三分钟跑起来

```bash
python start.py
```

然后打开 **http://127.0.0.1:18082/** 就是聊天界面。

想单独启：

```bash
cd ecommerce-service-backend && python main.py    # 中台 18081
cd customer-service-backend  && python main.py    # 客服 18082
```

**依赖**：Python 3.12+，`fastapi uvicorn pydantic pydantic-settings jinja2 sqlalchemy aiosqlite httpx langchain langchain-openai`。
数据库默认 SQLite，**无需安装 MySQL、无需执行建表脚本**，首次启动自动建表并灌演示数据。

### 接真实大模型（可选）

编辑 `customer-service-backend/.env`：

```ini
LLM_API_KEY=sk-你的key
LLM_MODEL=qwen-plus
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

重启即生效，右上角标签会从「本地规则引擎」变成「大模型已接入」。

**不填 key 也能完整演示**：`infrastructure/llm.py` 内置了一套规则引擎，按同一套
`BaseChatModel` 接口实现了意图规划、知识作答、澄清、闲聊四种输出，所以三条轨道、
多轮补槽、任务挂起恢复全都能跑，只是措辞不如真模型灵活。

---

## 二、它能做什么

| 轨道 | 能力 | 示例 |
|---|---|---|
| **任务流程** | 查订单状态、查物流、申请退款、相似商品推荐、转人工 | "我的快递到哪了" → 问订单号 → 报物流轨迹 |
| **知识检索** | 商品/订单实时查询（走中台 API）、退款/退货/配送政策（FAQ）、平台规则（RAG） | "退款多久能到账" → 直接答 1-3 个工作日 |
| **闲聊兜底** | 打招呼、寒暄、听不懂时的柔化回应 | "你好" → 自我介绍 + 能力清单 |

**核心体验**：点右侧订单卡片，再说"我要退款"，系统直接跳到"请说明退款原因"——
订单号已经从卡片自动填进槽位，不再追问一轮。这就是"对象消息"的价值：把"用户此刻在指哪个东西"
变成结构化输入，而不是让模型从一句话里猜。

---

## 二点五、界面

单页原生 JS，无框架无构建，直接由客服后端托管在根路径。

- **空状态**：四个能力卡片（查订单 / 查物流 / 申请退款 / 售后政策），点一下直接发起对话，
  比让人面对空白输入框强。
- **对话态**：机器人白底描边气泡、用户品牌渐变气泡，靠头像一侧收小圆角；三条轨道回复都带打字动画。
  有消息后底部才会浮出快捷话术条，首屏不堆按钮。
- **对象区**：订单/商品卡片带色块缩略图（品类/状态配色）、状态徽章、价格；hover 才显示"发给客服"，
  平时不抢注意力。加载中是骨架屏而不是转圈。
- **多用户**：右上角切换账号会同时刷新对话历史和订单商品，三个演示账号中 `u1003` 是干净账号（无历史），
  适合演示首次进入。
- **响应式**：< 820px 自动改为上下布局，聊天区与对象区各自独立滚动。

配色只用一套暖橙品牌色 + 中性灰，所有间距走 8 的倍数，没有引入任何外部字体或图标库——
图标全部内联 SVG，所以断网也不会掉样式。

---

## 三、架构

```
customer-service-frontend/      单页聊天界面（原生 JS，无构建步骤）
ecommerce-service-backend/      模拟电商中台：用户/商品/订单/物流/售后接口（18081）
customer-service-backend/       AI 客服核心（18082）
├── app/
│   ├── api/            FastAPI 实例、路由、Pydantic 出入参、依赖注入
│   ├── service/        编排：load_state → engine → save_state
│   ├── engine/         DialogueEngine（调度中枢）+ builder（装配工厂）
│   ├── plan/           TurnPlanner（LLM 规划）+ TurnPlanValidator（防幻觉）
│   ├── clarify/        校验不过时的澄清话术
│   ├── task/           handler / command（4 种命令）/ flow（YAML 执行器）/ action
│   ├── knowledge/      intents / providers（API·FAQ·RAG）/ registry / responder
│   ├── chitchat/       闲聊 handler + responder
│   ├── domain/         DialogueState 聚合根、消息、上下文（判别联合）
│   ├── repository/     dialogue_states 表读写（upsert）
│   ├── infrastructure/ DB 引擎、LLM 客户端、中台 HTTP 客户端
│   ├── prompts/        Jinja2 提示词模板（4 个）+ 历史渲染
│   └── conf/           pydantic-settings 读 .env
└── flow_config/        user_flows.yml（6 条业务流）+ system_flows.yml（6 条过场）
```

一条消息的旅程：

```
POST /api/chat
  → DialogueService.load_state
  → DialogueEngine.process_message
      ├─ 文本消息 → TurnPlanner 出 TurnPlan → Validator 安检
      │              ├─ 不通过 → ClarifyResponder 追问
      │              └─ 通过   → Task / Knowledge / Chitchat 三条轨道之一
      └─ 对象消息 → 记 focused_object + 尝试补槽
  → 保存 DialogueState（SQLite upsert）
  → 返回 BotMessage 列表
```

---

## 四、几处关键实现

有 8 个地方不是照着直觉写就能跑通的，代码里都留了注释说明原因，这里集中列一下：

1. **`engine/builder.py` / `conf/config.py`**：路径层级。`config.py` 在 `app/conf/` 下，
   写死 `parents[1]` 实际指向 `app/` 而非工程根，`.env` 和 `flow_config` 都会找不到 →
   装配工厂取 `parents[2]`，配置模块改为向上探测含 `.env` / `flow_config` 的目录。
2. **`repository/dialogue_state_repository.py`**：MySQL 的 `on_duplicate_key_update` 和
   SQLite 的 `on_conflict_do_update` 语法不通用，写死任何一边另一边都会语法错 →
   按 `session.get_bind().dialect.name` 分支构造。
3. **`service/dialogue_service.py`**：历史接口要的是 `HistoryMessage`，而 `HistoryBuilder`
   只提供给提示词用的 `_render_user_message(msg) -> str`，签名和返回类型都对不上 →
   在 service 层直接转换，不让接口层反向依赖提示词层。
4. **`plan/turn_planner.py`**：`knowledge_intents_json` 若留空串，LLM 不知道有哪些合法意图，
   知识轨永远规划不出来 → 注入 `KNOWLEDGE_INTENTS` 清单。
5. **`task/action/custom/recommend_similar_products.py`**：中台返回的字段叫 `name` 而不是
   `title`，读错就永远只显示商品 ID → 修正字段名并做成真实同品类召回。
6. **`task/command/processor.py`**：`resume_flow` 若复用"打断"过场，用户说"继续"却回
   "先把 A 放一放" → 改用恢复专属的系统过场。
7. **`main.py`**：包内是 `from api.app import app` 这种以 `app` 为根的绝对导入，
   直接 `python main.py` 会 ModuleNotFoundError → 启动前把 `app/` 插进 `sys.path`。
8. **`infrastructure/llm.py`**：没有 API Key 时降级为规则引擎，按同一套 `BaseChatModel`
   接口实现规划、知识、澄清、闲聊四种输出，保证三条轨道离线也能完整跑通。

配套部分：`models/init_db.py`（启动即自动建表）、`knowledge/faq_data.py`（FAQ / RAG 语料）、
`ecommerce-service-backend/`（模拟电商中台，用户 / 商品 / 订单 / 物流 / 售后接口）、
`customer-service-frontend/`（单页聊天界面）。

---

## 五、已验证的用例

全部经过真实 HTTP 调用验证（非单测桩）：

| 场景 | 结果 |
|---|---|
| 查订单状态（两轮补槽） | 订单 A20240315001 当前状态：已发货，金额 ¥129，商品：轻薄连帽防晒衣 |
| 查物流 | 顺丰速运，单号 SF1234567890，运输中预计明天送达 |
| 申请退款（两轮补槽） | 收集订单号 → 原因 → 提交成功 |
| 点订单卡片 + "我要退款" | 跳过订单号追问，直接问原因 |
| 退款/退货/配送/优惠券政策 | FAQ 精准命中并作答 |
| 点商品卡片 + "这个多少钱" | 查中台返回价格、库存、卖点 |
| 相似商品推荐 | 同品类召回：纯棉T恤 ¥79、牛仔裤 ¥199 |
| 转人工 | 正常转接话术 |
| 流程中取消 | 正确终止并提示 |
| 任务中断 + 恢复 | 挂起退款 → 查物流 → "继续刚才那个退款" 正确恢复 |
| 历史记录 | GET /api/chat/history 按 session 展开 |

---

## 六、换 MySQL（可选）

`.env` 里改一行：

```ini
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/customer_service
```

建表已做自动 `create_all`，不需要手工执行 SQL。仓储层的 upsert 会按方言自动切换。

---

## 七、这台机器上怎么推 GitHub

本机网络只有 `api.github.com` 可达，`github.com:443` 直连和走代理都超时，
因此 `git push` / `git fetch` 一律失败。改用 Git Data API 绕过去：

```bash
python tools/push_to_github.py            # 追加一次提交到远端 main
python tools/push_to_github.py --dry-run  # 只看要传哪些文件
python tools/push_to_github.py --orphan   # 用当前内容重建为单条提交
```

Token 取环境变量 `GH_TOKEN` / `GITHUB_TOKEN`，都没有就回落到 `gh auth token`。

两点说明：

- 远端提交由 API 重建，**sha 与本地提交不同**（作者时间、父提交都不一样），
  但每个文件的 blob sha 与本地完全一致，clone 下来内容逐字节相同；
- 请求带指数退避重试，单个 HTTPS 连接被掐断不会让整次推送失败。
