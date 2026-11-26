#!/usr/bin/env python
# ══════════════════════════════════════════════════════════════════════════
# 一键启动：同时拉起「模拟电商中台」和「AI 客服后端」
# 用法：python start.py        （Ctrl+C 一起停）
# ══════════════════════════════════════════════════════════════════════════
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SERVICES = [
    ("模拟电商中台", ROOT / "ecommerce-service-backend", 18081),
    ("AI 客服后端", ROOT / "customer-service-backend", 18082),
]


def main() -> None:
    procs = []
    for name, cwd, port in SERVICES:
        print(f"[start] 启动 {name}（端口 {port}）…")
        procs.append((name, subprocess.Popen([sys.executable, "main.py"], cwd=str(cwd))))

    print()
    print("=" * 56)
    print("  聊天界面  http://127.0.0.1:18082/")
    print("  接口文档  http://127.0.0.1:18082/docs")
    print("  中台文档  http://127.0.0.1:18081/docs")
    print("=" * 56)
    print("Ctrl+C 停止全部服务")

    try:
        while True:
            for name, p in procs:
                code = p.poll()
                if code is not None:
                    print(f"[start] {name} 已退出（code={code}），停止其余服务")
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        for name, p in procs:
            if p.poll() is None:
                p.terminate()
        print("\n[start] 已停止")


if __name__ == "__main__":
    main()
