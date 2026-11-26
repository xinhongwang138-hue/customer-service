# models/init_db.py ｜ 建表工具：把 ORM 元数据落成真实数据库表
# 被谁调用：api/app.py 的 lifespan（启动时建表，幂等）
# 为什么需要：ORM 只声明了映射关系，不等于库里真有表；
#         用 create_all 后 SQLite/MySQL 都能"起服务即建表"，省掉手工执行 SQL。

# app/models/init_db.py


async def create_tables() -> None:
    """创建所有已注册到 Base.metadata 的表（已存在则跳过，可反复调用）。"""
    # 函数内导入：engine 是模块级全局变量，必须在 init_db_engine() 之后才取到真值
    from infrastructure import database
    from models.base import Base
    # noqa 这行只为"注册模型到 metadata"，不显式使用
    from models.dialogue_state import DialogueStateRecord  # noqa: F401

    if database.engine is None:
        return

    async with database.engine.begin() as conn:
        # run_sync：把同步的 create_all 放进异步引擎执行
        await conn.run_sync(Base.metadata.create_all)
    print("[init_db] 数据表已就绪：dialogue_states")
