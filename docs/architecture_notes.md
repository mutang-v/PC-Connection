# 当前模块化架构

```text
手机浏览器
    │ HTTP / JSON（局域网）
    ▼
companion/http_api.py  —— 路由与静态页面
    ├── companion/metrics.py —— 只读系统指标
    ├── companion/actions.py —— 固定操作白名单
    └── companion/config.py —— 监听地址和端口

server.py —— 启动入口
web/index.html —— 现有中文监控 UI
```

## 本轮原则
- 保持 `/api/stats`、`/api/processes`、`/api/action` 路径，尽量不破坏现有前端。
- 将指标采集、操作执行、HTTP 路由分开，后续可独立测试和替换。
- 不新增大型框架；只依赖已有的 Python 与 `psutil`。
- 当前还不是正式安全远控产品：后续在新增操作前先实现设备配对、认证、请求防护与操作审计。

## 后续迁移顺序
1. 在 Windows 实机验证此版本与旧版数据一致。
2. 为 API 增加设备配对与认证，明确网络信任边界。
3. 加入结构化日志、配置文件与版本信息。
4. 将网页逐步替换为 Android 客户端，保留 Windows 服务作为数据与控制端。
5. 每次新增控制操作均采用固定动作 ID、参数白名单和确认机制。
