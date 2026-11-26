# ══════════════════════════════════════════════════════════════════════════
# 文件职责：创建 FastAPI 应用实例并注册路由，用 lifespan 管理数据库引擎启停
# 所在层：API 层（api 包的根模块）
# 被谁调用：main.py 里 uvicorn.run("api.app:app") 按字符串导入
# ══════════════════════════════════════════════════════════════════════════
# app/api/app.py

# 模块文档字符串：本文件职责是定义 FastAPI 实例
"""
定义fastapi实例

"""
# asynccontextmanager：把 async 生成器函数包装成"异步上下文管理器"
from contextlib import asynccontextmanager
# Path：定位同级的前端目录
from pathlib import Path

# FastAPI：Web 框架，靠类型注解自动完成校验与接口文档
from fastapi import FastAPI
# StaticFiles：把前端单页托管到根路径，省掉单独起前端服务
from fastapi.staticfiles import StaticFiles

# settings：读电商中台地址（/api/meta 里回显给前端）
from conf.config import settings

# router：聊天路由（POST /api/chat 等接口都定义在其中）
from api.routers.chat_router import router
# init_db_engine / close_db_engine：数据库连接池的初始化与关闭函数
from infrastructure.database import init_db_engine, close_db_engine
# create_tables：按 ORM 元数据建表（幂等，首次启动自动建好 dialogue_states）
from models.init_db import create_tables
# init_http_client / close_http_client：电商中台 HTTP 客户端的初始化与关闭
from infrastructure.http_client import init_http_client, close_http_client


# 该装饰器让下面的生成器函数具备"启动→运行→关闭"三段式生命周期
@asynccontextmanager
# lifespan：在应用启动/关闭时挂载钩子，yield 前后做资源创建与释放
async def lifespan(app: FastAPI):
    """
    应用生命周期管理：
        - 启动时：执行 yield 前的代码（初始化数据库引擎）
        - 运行中：yield 让出控制权，FastAPI 处理请求
        - 关闭时：执行 yield 后的代码（关闭数据库引擎）

    注意：
        - app 参数必须指定，类型为 FastAPI
        - 可通过 app.state 存储全局共享资源（当前未使用）
    """
    # 1. 应用启动
    # 打印启动日志，方便观察应用何时进入服务状态
    print("启动服务器...")
    # 初始化全局数据库引擎：创建连接池，之后请求复用
    init_db_engine()  # ← 执行这里，创建数据库连接池
    # 建表：SQLite 下首次启动自动创建 dialogue_states，无需手工执行 SQL 脚本
    await create_tables()
    # 初始化 HTTP 客户端：知识轨道/查询类 action 调电商中台要用
    init_http_client()

    # 2. 进入 yield
    # yield 让出控制权给 FastAPI，它才真正开始接收请求
    yield  # ← FastAPI 开始接收请求
    #    用户访问 API...
    #    用户访问 API...

    # 3. 应用关闭（Ctrl+C 或部署平台停止）
    # await 异步关闭连接池，把占用的连接全部释放
    await close_db_engine()  # ← 执行这里，关闭连接池
    await close_http_client()  # 释放 HTTP 连接池
    # 关闭日志，至此整个生命周期结束
    print("服务器已关闭")


# 创建 FastAPI 实例：description 写入文档，lifespan 挂载生命周期
app = FastAPI(description="电商小二智能客服应用", lifespan=lifespan)

# 注册路由：把聊天接口挂进 app，URL 才会对外生效
app.include_router(router)


# ══════════════════════════════════════════════════════════════════════════
# 运行状态：前端据此显示当前是"真实大模型"还是"本地规则引擎"
# ══════════════════════════════════════════════════════════════════════════
@app.get("/api/meta")
def meta():
    from infrastructure.llm import llm

    offline = getattr(llm, "_llm_type", "") == "offline-rule"
    return {
        "llm": "offline-rule" if offline else getattr(llm, "_llm_type", "unknown"),
        "offline": offline,
        "commerce_api": settings.commerce_api_base_url,
    }


# ══════════════════════════════════════════════════════════════════════════
# 托管前端：访问 http://127.0.0.1:18082/ 直接就是聊天界面
# （必须放在所有路由注册之后，否则 mount 会抢走 /api/* 的匹配）
# ══════════════════════════════════════════════════════════════════════════
_FRONTEND_DIR = Path(__file__).resolve().parents[3] / "customer-service-frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
