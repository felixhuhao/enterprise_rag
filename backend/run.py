"""
Uvicorn 服务器启动入口

通过 uvicorn ASGI 服务器运行 FastAPI 应用。
启用 reload 模式，开发时代码修改会自动重启服务。

启动方式：python run.py
监听地址：0.0.0.0:8010（所有网络接口，端口 8010）
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8010, reload=True)
