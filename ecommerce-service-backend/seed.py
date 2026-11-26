# ══════════════════════════════════════════════════════════════════════════
# 文件职责：灌入演示用的种子数据（用户 / 商品 / 订单 / 物流）
# 所在层：数据初始化
# 被谁调用：main.py 启动时调用 seed_if_empty()，库里已有数据就跳过
# ══════════════════════════════════════════════════════════════════════════

from datetime import datetime

from sqlalchemy import select

from db import SessionLocal
from models import Logistics, Order, OrderItem, Product, User


def seed_if_empty() -> None:
    """只在空库时灌数据，避免每次重启重复插入。"""
    with SessionLocal() as s:
        if s.execute(select(User)).first() is not None:
            return

        s.add_all([
            User(id="u1001", name="张小明", phone="13800001111"),
            User(id="u1002", name="李小红", phone="13900002222"),
            # 第三个账号是"干净账号"：没有对话历史，用来演示空状态 / 首次进入
            User(id="u1003", name="王小二", phone="13700003333"),
        ])

        s.add_all([
            Product(id="P1001", name="轻薄连帽防晒衣", price=129, stock=120,
                    category="服饰",
                    description="UPF50+ 原纱防晒，轻薄透气，可收纳进随身小包，适合春夏通勤与户外。"),
            Product(id="P1002", name="纯棉基础T恤", price=79, stock=300,
                    category="服饰",
                    description="260g 重磅纯棉，不易变形，圆领基础款，四季可穿。"),
            Product(id="P1003", name="高腰直筒牛仔裤", price=199, stock=58,
                    category="服饰",
                    description="高腰直筒版型，显腿长，微弹面料，久坐不勒。"),
            Product(id="P1004", name="轻便透气运动鞋", price=259, stock=0,
                    category="鞋靴",
                    description="网面透气，单只约 220g，适合日常通勤与轻运动。"),
        ])

        # ── 订单 1：已发货、有物流轨迹（查订单/查物流的演示主角）──
        s.add(Order(
            order_number="A20240315001", user_id="u1001",
            status="shipped", status_desc="已发货",
            amount=129, created_at=datetime(2026, 11, 24, 9, 12),
            items=[OrderItem(product_id="P1001", title_snapshot="轻薄连帽防晒衣",
                             price=129, quantity=1)],
            logistics=Logistics(
                tracking_number="SF1234567890", logistics_company="顺丰速运",
                status="in_transit", status_desc="运输中，预计明天送达",
                traces="\n".join([
                    "2026-11-24 09:12|商家已发货，等待揽收",
                    "2026-11-24 15:40|顺丰速运已揽收",
                    "2026-11-25 08:05|到达杭州转运中心",
                    "2026-11-26 07:30|派送中，快递员 王师傅 138****8888",
                ]),
            ),
        ))

        # ── 订单 2：待发货、无物流（演示"还没发货"）──
        s.add(Order(
            order_number="A20240315002", user_id="u1001",
            status="paid", status_desc="待发货",
            amount=199, created_at=datetime(2026, 11, 25, 20, 3),
            items=[OrderItem(product_id="P1003", title_snapshot="高腰直筒牛仔裤",
                             price=199, quantity=1)],
        ))

        # ── 订单 3：已完成已签收（演示历史订单）──
        s.add(Order(
            order_number="A20240315003", user_id="u1002",
            status="completed", status_desc="已完成",
            amount=79, created_at=datetime(2026, 11, 18, 14, 20),
            items=[OrderItem(product_id="P1002", title_snapshot="纯棉基础T恤",
                             price=79, quantity=1)],
            logistics=Logistics(
                tracking_number="ZT9876543210", logistics_company="中通快递",
                status="delivered", status_desc="已签收",
                traces="2026-11-20 16:22|已签收，签收人：本人",
            ),
        ))

        # ── 订单 4：多商品、运输中 ──
        s.add(Order(
            order_number="A20240315004", user_id="u1002",
            status="in_transit", status_desc="运输中",
            amount=338, created_at=datetime(2026, 11, 23, 11, 45),
            items=[
                OrderItem(product_id="P1004", title_snapshot="轻便透气运动鞋",
                          price=259, quantity=1),
                OrderItem(product_id="P1002", title_snapshot="纯棉基础T恤",
                          price=79, quantity=1),
            ],
            logistics=Logistics(
                tracking_number="JD5566778899", logistics_company="京东物流",
                status="in_transit", status_desc="运输中",
                traces="2026-11-24 10:00|京东物流已揽收\n2026-11-25 19:30|已到达目的地分拣中心",
            ),
        ))

        # ── 订单 5：干净账号的首单（演示空状态进入后先看到一张订单）──
        s.add(Order(
            order_number="A20240315005", user_id="u1003",
            status="paid", status_desc="待发货",
            amount=158, created_at=datetime(2026, 11, 26, 8, 30),
            items=[OrderItem(product_id="P1002", title_snapshot="纯棉基础T恤",
                             price=79, quantity=2)],
        ))

        s.commit()
        print("[seed] 演示数据已写入：3 个用户 / 4 个商品 / 5 张订单")
