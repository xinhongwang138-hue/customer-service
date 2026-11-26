# ══════════════════════════════════════════════════════════════════════════
# 文件职责：模拟电商中台（业务后端）——给 AI 客服提供订单 / 物流 / 商品数据
# 所在层：独立服务（不属于客服后端，扮演真实企业里的"业务中台"）
# 被谁调用：客服后端的 infrastructure/http_client.py 与 knowledge/providers.py
# 设计要点：全部同步实现。CRUD 单次 < 50ms，异步在这里是负担不是优势。
# ══════════════════════════════════════════════════════════════════════════

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

from db import Base, SessionLocal, engine
from models import Logistics, Order, Product, RefundApplication, ShippingReminder, User
from seed import seed_if_empty


# ── 统一响应包装：所有接口都返回 {code, msg, data} ──────────────────────────
def ok(data=None, msg: str = "ok") -> dict:
    return {"code": 0, "msg": msg, "data": data}


def fail(msg: str, code: int = 404) -> dict:
    return {"code": code, "msg": msg, "data": None}


# ── 序列化：ORM → 前端/客服能直接消费的 dict ────────────────────────────────
def product_to_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "price": float(p.price or 0),
        "stock": p.stock,
        "stock_status": "有货" if (p.stock or 0) > 0 else "缺货",
        "description": p.description or "",
        "category": p.category or "",
    }


def order_to_dict(o: Order) -> dict:
    return {
        "order_number": o.order_number,
        "user_id": o.user_id,
        "status": o.status,
        "status_desc": o.status_desc,
        "amount": float(o.amount or 0),
        "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else None,
        "items": [
            {
                "product_id": i.product_id,
                "title_snapshot": i.title_snapshot,
                "price": float(i.price or 0),
                "quantity": i.quantity,
            }
            for i in o.items
        ],
    }


def logistics_to_dict(l: Logistics) -> dict:
    traces = []
    for line in (l.traces or "").split("\n"):
        if "|" in line:
            t, desc = line.split("|", 1)
            traces.append({"time": t.strip(), "desc": desc.strip()})
    return {
        "order_number": l.order_number,
        "tracking_number": l.tracking_number,
        "logistics_company": l.logistics_company,
        "status": l.status,
        "status_desc": l.status_desc,
        "traces": traces,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表 + 灌种子数据（幂等，可反复启动）
    Base.metadata.create_all(engine)
    seed_if_empty()
    print("[commerce] 模拟电商中台已就绪 http://127.0.0.1:%s" % os.getenv("COMMERCE_PORT", "18081"))
    yield


app = FastAPI(title="模拟电商中台 ecommerce-service-backend", lifespan=lifespan)

# 直接放开跨域：前端 5173 / 客服后端 18082 都要能调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
# 健康检查
# ════════════════════════════════════════════════════════════════════════════
@app.get("/health")
def health():
    return ok({"status": "up"})


# ════════════════════════════════════════════════════════════════════════════
# 用户
# ════════════════════════════════════════════════════════════════════════════
@app.get("/users")
def list_users():
    """前端"当前用户"下拉框用。"""
    with SessionLocal() as s:
        users = s.execute(select(User)).scalars().all()
        return ok([{"id": u.id, "name": u.name, "phone": u.phone} for u in users])


# ════════════════════════════════════════════════════════════════════════════
# 商品
# ════════════════════════════════════════════════════════════════════════════
@app.get("/products")
def list_products():
    with SessionLocal() as s:
        products = s.execute(select(Product)).scalars().all()
        return ok([product_to_dict(p) for p in products])


@app.get("/products/{product_id}")
def get_product(product_id: str):
    with SessionLocal() as s:
        p = s.get(Product, product_id)
        if p is None:
            return fail(f"商品 {product_id} 不存在")
        return ok(product_to_dict(p))


# ════════════════════════════════════════════════════════════════════════════
# 订单
# ════════════════════════════════════════════════════════════════════════════
@app.get("/users/{user_id}/orders")
def list_user_orders(user_id: str):
    """某用户最近订单列表（前端右侧订单卡片区）。"""
    with SessionLocal() as s:
        orders = s.execute(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
        ).scalars().all()
        return ok([order_to_dict(o) for o in orders])


@app.get("/users/{user_id}/products")
def list_user_products(user_id: str):
    """某用户"最近商品"：从他自己的订单明细里去重提取，再拼商品详情。"""
    with SessionLocal() as s:
        orders = s.execute(select(Order).where(Order.user_id == user_id)).scalars().all()
        seen: list[str] = []
        for o in orders:
            for item in o.items:
                if item.product_id not in seen:
                    seen.append(item.product_id)
        products = []
        for pid in seen[:6]:
            p = s.get(Product, pid)
            if p is not None:
                products.append(product_to_dict(p))
        return ok(products)


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if o is None:
            return fail(f"订单 {order_id} 不存在")
        return ok(order_to_dict(o))


@app.get("/orders/{order_id}/status")
def get_order_status(order_id: str):
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if o is None:
            return fail(f"订单 {order_id} 不存在")
        return ok({
            "order_number": o.order_number,
            "status": o.status,
            "status_desc": o.status_desc,
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else None,
        })


@app.get("/orders/{order_id}/logistics")
def get_logistics(order_id: str):
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if o is None:
            return fail(f"订单 {order_id} 不存在")
        if o.logistics is None:
            return fail(f"订单 {order_id} 暂无物流信息（可能还未发货）")
        return ok(logistics_to_dict(o.logistics))


# ════════════════════════════════════════════════════════════════════════════
# 售后：退款申请 / 催发货
# ════════════════════════════════════════════════════════════════════════════
class RefundPayload(BaseModel):
    reason: str = ""


@app.post("/orders/{order_id}/refund-applications")
def create_refund(order_id: str, payload: RefundPayload | None = None):
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if o is None:
            return fail(f"订单 {order_id} 不存在")
        record = RefundApplication(
            order_number=order_id,
            reason=(payload.reason if payload else "") or "未填写",
        )
        s.add(record)
        s.commit()
        return ok({
            "id": record.id,
            "order_number": order_id,
            "reason": record.reason,
            "status": record.status,
        })


@app.post("/orders/{order_id}/shipping-reminders")
def create_shipping_reminder(order_id: str):
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if o is None:
            return fail(f"订单 {order_id} 不存在")
        record = ShippingReminder(order_number=order_id)
        s.add(record)
        s.commit()
        return ok({"id": record.id, "order_number": order_id, "message": "已通知商家尽快发货"})


if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host=os.getenv("COMMERCE_HOST", "127.0.0.1"),
        port=int(os.getenv("COMMERCE_PORT", "18081")),
    )
