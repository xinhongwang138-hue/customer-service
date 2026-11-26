# ══════════════════════════════════════════════════════════════════════════
# 文件职责：用 pydantic-settings 从 .env 读取并校验全局配置
# 所在层：配置层（conf 包，属基础设施范畴）
# 被谁调用：main.py、api 层等 from conf.config import settings 使用
# ══════════════════════════════════════════════════════════════════════════
# app/conf/config.py

# Path：跨平台路径处理，用来定位项目根目录下的 .env 文件
from pathlib import Path

# BaseSettings 让字段自动读环境变量；SettingsConfigDict 配置读取方式
from pydantic_settings import BaseSettings, SettingsConfigDict

def _find_project_root() -> Path:
    """从当前文件向上找，第一个含 .env 或 flow_config 的目录即项目根。

    config.py 位于 app/conf/ 下，固定的相对层级（如 parents[1]）指向的是
    app/ 而不是项目根，会导致 .env 读不到。这里改为逐级向上探测，更稳。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env").exists() or (parent / "flow_config").exists():
            return parent
    return here.parents[2]


# ENV_FILE：.env 的绝对路径（项目根目录下）
ENV_FILE = _find_project_root() / ".env"

# 配置文件的 模型类  有校验功能
# Settings 继承 BaseSettings：每个带注解的类属性即一项配置，自动校验
class Settings(BaseSettings):

    # LLM
    # 大模型 API 密钥，对应 .env 中的 LLM_API_KEY
    llm_api_key: str
    # 大模型名称，请求时决定调用哪个模型
    llm_model: str
    # 大模型服务地址（兼容 OpenAI 协议的 base_url）
    llm_base_url: str

    # 数据库
    # 数据库连接串：驱动+账号+地址+库名，用于创建异步连接池
    database_url: str

    # 商城 API
    # 商城系统接口根地址：查订单/商品等数据时调用
    commerce_api_base_url: str

    # 服务器
    # 服务监听地址，如 0.0.0.0 表示对外网开放
    app_host: str
    # 服务监听端口，声明 int 会自动做类型转换与校验
    app_port: int

    # 从.env文件中读取配置信息
    # 如果读取真实环境变量，则不写这句话
    # extra="ignore" 表示忽略.env中有，这里没有的配置项，不会报错
    # env_file_encoding：如果遇到乱码问题则添加这个属性解决
    # 注意这里对象名必须叫model_config ，而且必须定义，否则配置会被回收
    # 继承 BaseSettings 里面也提供一系列 默认 的属性
    # 配置元数据：指定 .env 路径、忽略多余键、utf-8 解码
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", env_file_encoding="utf-8")

# 实例化全局唯一配置对象：import 即解析 .env，全项目共享
settings = Settings()


if __name__ == '__main__':
    # 直接运行本文件时做自测：验证配置能否正常读取

    from conf.config import settings

    # 打印一项配置，肉眼确认 .env 解析结果
    print(settings.llm_base_url)
