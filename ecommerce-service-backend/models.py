# ══════════════════════════════════════════════════════════════════════════
# 文件职责：模拟电商中台的 ORM 模型（用户 / 商品 / 订单 / 订单明细 / 物流 / 申请单）
# 所在层：数据模型层
# 被谁调用：main.py 查询、seed.py 灌种子数据
# ══════════════════════════════════════════════════════════════════════════

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class User(Base):
    """用户：客服前端左侧的"当前登录用户"就从这里来。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="")


class Product(Base):
    """商品。"""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="")


class Order(Base):
    """订单主表。status 存机器码，status_desc 存给人看的中文。"""

    __tablename__ = "orders"

    order_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    status_desc: Mapped[str] = mapped_column(String(64), default="待付款")
    amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    logistics: Mapped["Logistics | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class OrderItem(Base):
    """订单明细：title_snapshot 是下单时的商品名快照（商品改名不影响历史订单）。"""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), ForeignKey("orders.order_number"), index=True)
    product_id: Mapped[str] = mapped_column(String(32))
    title_snapshot: Mapped[str] = mapped_column(String(128), default="")
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    order: Mapped[Order] = relationship(back_populates="items")


class Logistics(Base):
    """物流单：一个订单最多一条。"""

    __tablename__ = "logistics"

    order_number: Mapped[str] = mapped_column(
        String(32), ForeignKey("orders.order_number"), primary_key=True
    )
    tracking_number: Mapped[str] = mapped_column(String(64), default="")
    logistics_company: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    status_desc: Mapped[str] = mapped_column(String(255), default="")
    # 轨迹用 "时间|描述" 每行一条的纯文本存，读多写少，不值得单独建附表
    traces: Mapped[str] = mapped_column(Text, default="")

    order: Mapped[Order] = relationship(back_populates="logistics")


class RefundApplication(Base):
    """退款申请单：POST /orders/{id}/refund-applications 写入。"""

    __tablename__ = "refund_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ShippingReminder(Base):
    """催发货提醒：POST /orders/{id}/shipping-reminders 写入。"""

    __tablename__ = "shipping_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
