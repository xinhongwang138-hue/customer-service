# ══════════════════════════════════════════════════════════════════════════
# 文件职责：模拟电商中台的数据库连接（SQLite，零配置）
# 所在层：基础设施层
# 说明：真实企业里这一层接的是业务库；这里用 SQLite 免去装库成本，
#      想换 MySQL 只改 DATABASE_URL 一个环境变量即可。
# ══════════════════════════════════════════════════════════════════════════

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 数据库地址：默认落在本文件同级的 commerce.db
BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("COMMERCE_DATABASE_URL", f"sqlite:///{BASE_DIR / 'commerce.db'}")

# check_same_thread=False：FastAPI 的线程池会换线程访问同一连接，SQLite 需要放开这个检查
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""
