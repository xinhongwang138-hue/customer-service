# ══════════════════════════════════════════════════════════════════════════
# 文件职责：服务启动入口，用 uvicorn 拉起 FastAPI 应用并监听端口
# 所在层：应用入口（项目最顶层，不属于 api/domain/service 任一包）
# 被谁调用：命令行执行 python main.py 启动服务
# ══════════════════════════════════════════════════════════════════════════
# app/main.py

# 模块文档字符串：说明本文件的作用是"启动 uvicorn"
"""
启动uvicorn
"""
# sys / Path：把 app/ 目录加入模块搜索路径
import sys
from pathlib import Path

# uvicorn：Python 的 ASGI 服务器，负责把 FastAPI 应用跑成真实 HTTP 服务
import uvicorn

# 项目内部统一写 `from api.app import app` 这种"以 app 为根的绝对导入"，
# 所以启动前必须把 app/ 本身放进 sys.path（否则 import api 会失败）。
_PKG_ROOT = Path(__file__).resolve().parent / "app"
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# settings：全局唯一配置对象，host/port 都从 .env 解析而来
from conf.config import settings

# __name__=='__main__'：只有直接运行本文件才为真，被 import 时跳过
if __name__ == '__main__':
    # uvicorn.run：按"模块:应用对象名"定位并启动 FastAPI 应用
    uvicorn.run(
        app="api.app:app",
        host=settings.app_host,
        port=settings.app_port
    )
