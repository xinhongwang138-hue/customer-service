# infrastructure/database.py ｜ 基础设施层：全局"异步引擎 + 会话工厂"单例
# 被谁调用：应用启动(api/app.py)时 init、退出时 close；Repository 层从工厂取会话
# 依赖方向：基础设施是最底层，只被上层使用，绝不反向依赖业务代码

# app/infrastructure/database.py

# asyncio 提供事件循环，__main__ 自测时靠它运行 async 函数
import asyncio

# text() 可把原生 SQL 字符串包装成可执行对象（仅自测演示用）
from sqlalchemy import text
# 一次导入异步引擎/会话两大类型，以及两个工厂构造函数
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine, AsyncEngine

# 读取 conf.config 里的集中配置，例如数据库连接串
from conf.config import settings

# 声明  类型注释 描述变量 要用什么类型
# 模块级全局引擎变量，先占位 None，init 之后才真正创建
engine: AsyncEngine | None = None
# 模块级全局会话工厂变量，同样先占位 None，稍后赋值
async_session: async_sessionmaker[AsyncSession] | None = None
# 初始化
# 初始化函数：应用启动时调用一次，建立全局数据库连接资源
def init_db_engine() -> None:
    # global 声明：下面要改的是模块级全局变量，而非新建局部同名变量
    global engine, async_session

    # 1. 创建异步引擎
    # pool_pre_ping=True：取连接前先探活，自动重连，避免拿到已被服务端断开的连接。
    # 代价是每次多一次极轻的往返（ping），相对断连排查成本可以忽略。
    # 生产环境建议开启。

    # 创建异步连接池引擎；echo=True 会打印每句 SQL，便于调试
    engine = create_async_engine(settings.database_url, echo=True, pool_pre_ping=True)

    # async_sessionmaker：会话工厂。每请求一个 session，避免连接与事务状态互相污染，
    # 也让连接池的复用逻辑集中在一处配置。

    # 2. 创建异步session工厂

    # 把引擎包成"会话工厂"；expire_on_commit=False 使 commit 后属性仍可读
    async_session = async_sessionmaker(engine, expire_on_commit=False)

# 关闭资源
# 优雅释放全局资源；这是协程函数，调用时要 await
async def close_db_engine():
    # 防呆判断：引擎还没创建（None）就不做清理，直接跳过
    if engine is not None:    # 关闭连接
        # dispose 关闭连接池，并等待在途数据库操作自然结束
        await engine.dispose()


# 仅当"直接运行本文件"时才进入，被 import 时不执行，是自测入口
if __name__ == '__main__':
    # 先初始化引擎和工厂，后面的测试代码才有会话可用
    init_db_engine()


    # test 也声明为协程，因为内部全是要 await 的数据库 IO
    async def test():
        # async with 进入借一个会话，退出块时自动把连接归还连接池
        async with async_session() as session:

            #text() 就是一个“转换器”：
            # 它把一个普通的 Python 字符串转换成 SQLAlchemy 能识别的“可执行 SQL 对象”。
            # 注意：使用 text() 时，建议尽量使用占位符（如 :user_id）来传参，
            # 不要直接把变量拼接到字符串里，这样可以防止 SQL 注入攻击。
            # 执行原生 SQL；:sender_id 是占位符，字典传值防止 SQL 注入
            result = await session.execute(text("SELECT * FROM dialogue_states WHERE sender_id = :sender_id"), {"sender_id": 1})

            # data = result.fetchall()
            # fetchone 只取第一行；没有结果时返回 None（fetchall 是取全部行）
            data = result.fetchone()
            # 直接打印查到的整行数据，直观看看 Row 对象长什么样
            print(data)
            # 打印该对象类型，认识 SQLAlchemy 的 Row 而非普通元组
            print(type(data))

        # 自测收尾：关闭连接池，避免进程悬而不退
        await close_db_engine()


    # asyncio.run 创建并回收事件循环，异步代码必须经它启动
    asyncio.run(test())
