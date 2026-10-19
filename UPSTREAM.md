# WeKnora 对应关系

参考仓库：[Tencent/WeKnora](https://github.com/Tencent/WeKnora)。固定版本 0.8.3，提交 `2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5`。

本项目根据公开源码的执行结构重新实现为 Python；没有搬运 WeKnora 的数据库、事件总线、租户服务、存储、RAG、沙箱后端和 UI，也不需要 Go 或 Docker。

| WeKnora 来源 | 本版保留的思路 | 本版实现 |
|---|---|---|
| [engine.go:629](https://github.com/Tencent/WeKnora/blob/2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5/internal/agent/engine.go#L629) `executeLoop` | 轮次预算、取消、结束状态 | `lite_react/core.py` 的 `Agent.run` |
| [engine.go:744](https://github.com/Tencent/WeKnora/blob/2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5/internal/agent/engine.go#L744) `runReActIteration` | 模型决策 → 工具执行 → 结果观察 → 下一轮 | 同一极简主循环 |
| [think.go](https://github.com/Tencent/WeKnora/blob/2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5/internal/agent/think.go) | 模型适配器、临时故障处理 | `lite_react/ollama.py` 的同步 HTTP 请求 |
| [act.go](https://github.com/Tencent/WeKnora/blob/2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5/internal/agent/act.go) | 工具注册/调用、成功或错误观察 | `lite_react/tools.py`；工具串行执行 |
| [const.go](https://github.com/Tencent/WeKnora/blob/2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5/internal/agent/const.go) | 限次重试、空响应与卡住保护 | 显式轮次/工具/重复/格式预算 |

### 有意精简

- 模型请求改为非流式，阶段事件通过普通 Python 回调输出。
- 长上下文达到字符预算即停止；没有移植自动压缩、模型 tokenizer 校准和历史数据库。
- 不支持跨会话记忆、分叉回滚、动态 MCP 发现或多租户权限。
- 工具扩展是明确注册的 Python 函数；内置示例仅包含计算和只读文本操作。

### 额外实现，不能归因于上游

通用 Agent 核心没有统一的答案 `confidence` 自评协议；WeKnora 的检索/重排分数也不等于答案正确概率。LiteReAct 的 `confidence / needs_more / feedback` 自评、低分反馈再迭代及 JSON 决策模式是本项目新增的轻量机制。默认自评可关闭，不声称与上游评分行为一致。

完整上游许可保留在 `licenses/WeKnora-LICENSE.txt`。项目不是腾讯官方发行版。
