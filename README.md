# LiteReAct 1.0.0

一个从 WeKnora 调度思路中精简出来的本地 Agent 框架。保留 **Think → Act → Observe**、工具注册、错误反馈、有限迭代和停止条件；接入 Ollama。没有数据库、Web 服务、多租户、RAG、MCP 服务或企业级依赖，Python 源码只使用标准库。

本仓库包含 **完整源码、CLI、测试、示例和构建脚本**。Windows 便携 EXE、`runtime/` 和模型权重不在此仓库，需按 `build-windows.ps1` 或单独发布的离线包获取。

## 快速开始

需要 Python 3.10+ 和本地 [Ollama](https://ollama.com/download)（仅真实模型调用需要）。源码没有第三方运行依赖，无需 `pip install`。

```sh
python run.py --demo                  # 离线脚本演示，不调用 Ollama
python -m unittest discover -s tests -v
ollama pull qwen3:4b                  # 任选本机已有模型
python run.py "计算 (11434+12341)*412" --model qwen3:4b
```

首次使用可复制配置示例：

```sh
cp config.example.json config.json
```

`config.json` 已被 `.gitignore` 排除；相对 `workspace` 以配置文件所在目录为基准。把待处理的 UTF-8 文本或 Markdown 放进 `workspace/`，或用 `--workspace` 指定目录。内置文件工具只读取选定目录，不负责 PDF/Office 解析。

可直接尝试：

- `用计算工具计算 10000 元按年利率 3% 复利 5 年后的金额。`
- `列出工作目录文件，读取 welcome.txt，然后总结它的使用说明。`
- `在工作目录搜索“利率”，列出文件名、行号和相关内容。`

常用命令：

```sh
python run.py "总结目录里的文本" --workspace "./notes"
python run.py "计算 42*17" --model qwen3:4b --no-review
python run.py "计算 42*17" --mode json
python run.py "搜索项目说明" --json --trace trace.jsonl
python run.py --demo --json
python run.py --doctor
```

`--json` 输出答案、终止状态、轮数、工具次数、评分和事件；进程只在 `completed` 时返回 0，未完整完成的状态返回 2，连接检查失败返回 1。交互模式每条任务独立运行，输入 `/exit` 退出。`Ctrl+C` 中断当前调用；框架也可接收取消事件。

## 调度流程

```text
用户任务
   ↓
Think：模型决定调用工具，或给出候选答案
   ↓ 调用工具
Act：校验工具名与参数 → 执行已注册函数
   ↓
Observe：把成功结果/结构化错误回送模型
   └──────────────────────────→ 下一轮 Think

候选答案 → 可选自评 → 达到要求则结束
                       ↓ 自评低或仍有缺口
                 反馈给下一轮，再取证或修正
```

默认最多 10 个主决策轮、24 次工具调用、每轮 4 次调用，相同工具加相同参数最多执行 2 次。每个工具结果最多保留 6000 字符；消息上下文达到字符预算时停止并返回明确状态，不会悄悄切断工具调用/结果配对。工具按模型给出的顺序串行执行，便于理解和扩展。

模型 HTTP 临时故障可重试，**工具不会因为模型 HTTP 重试而自动重放**。无效参数和工具异常作为观察反馈给下一轮；未知工具、空响应、格式错误、重复调用和预算耗尽均有明确处理。本版采用非流式模型请求，终端显示阶段事件，不输出或保存模型的隐藏思维过程。

## 置信度的含义

WeKnora 通用 Agent 核心没有可直接移植的统一答案自评分，本版的评分是**额外实现的可选机制**：同一个本地模型根据任务、候选答案和工具证据，输出 `confidence`、`needs_more` 和一条简短改进意见。

默认 `min_confidence=0.65`、最多 2 次再迭代。这个分数是**未经校准的模型自评，不是答对概率，也不是独立验证器**。自评缺失/格式错误时返回 `review_unavailable`，评分为 `null`；改进预算耗尽仍低分或仍有证据缺口时返回 `low_confidence`，保留草稿。用 `--no-review` 或配置 `review: false` 可以只运行最小 ReAct 循环，减少额外模型调用。

## Ollama 两种模式

- **native（默认）**：向 `/api/chat` 发送原生 `tools`，把 assistant 的 `tool_calls` 和后续 `role=tool` 的结果成对回送。使用支持工具调用的模型。
- **json**：向模型提供工具说明，使用结构化 JSON 输出 `tool` / `finish` 决策；无需模型支持原生工具调用，但仍依赖模型遵守 JSON schema。

如果出现 `model does not support tools`，换支持工具的模型，或将 `mode` 改为 `json`。如果自评输出不稳定，先用 `--no-review`。生成触及输出上限时不会执行可能残缺的工具调用；可提高 `num_predict` 或缩小任务。请求超时由 `timeout` 控制，较慢的本地模型可以适当调高。

协议按 [Ollama Chat API](https://docs.ollama.com/api/chat) 与 [工具调用文档](https://docs.ollama.com/capabilities/tool-calling) 实现。模型名称只是配置示例，不包含模型权重或任何云端账号。

## 配置

默认读取程序旁的 `config.json`，也可以用 `--config` 指定路径。配置中的相对 `workspace` 以配置文件所在目录为基准；命令行的 `--workspace` 以终端当前目录为基准。命令行参数优先。

| 字段 | 默认值 | 用途 |
|---|---|---|
| `model` / `host` | `qwen3:4b` / `http://127.0.0.1:11434` | 模型与服务地址 |
| `workspace` | `workspace` | 文件工具范围 |
| `mode` | `native` | `native` 或 `json` |
| `max_rounds` | 10 | 主决策轮上限，不含自评调用 |
| `max_tool_calls` / `max_calls_per_round` | 24 / 4 | 总工具预算 / 单轮预算 |
| `repeat_limit` | 2 | 同名工具同参数的执行上限 |
| `review` / `min_confidence` | true / 0.65 | 是否自评 / 接受阈值 |
| `max_refinements` | 2 | 自评后最多改进次数，仍受总轮数限制 |
| `max_observation_chars` | 6000 | 单次工具观察文本长度 |
| `max_context_chars` | 40000 | 消息的序列化字符预算，并非精确 token 计数 |
| `timeout` / `retries` | 120 / 2 | 单次 HTTP 请求秒数 / 临时故障重试数 |
| `temperature` | 0.2 | 模型温度 |
| `num_ctx` / `num_predict` | 8192 / 2048 | Ollama 上下文 / 生成 token 配置 |

## 作为框架使用

```python
from lite_react import Agent, AgentConfig, OllamaClient, builtin_tools

tools = builtin_tools("workspace")

@tools.register("celsius_to_fahrenheit", "Convert Celsius to Fahrenheit", {
    "type": "object",
    "properties": {"celsius": {"type": "number"}},
    "required": ["celsius"],
    "additionalProperties": False,
})
def convert(celsius):
    return {"fahrenheit": celsius * 9 / 5 + 32}

agent = Agent(OllamaClient("qwen3:4b"), tools, AgentConfig(review=False))
result = agent.run("用工具将 25 摄氏度转换成华氏度")
print(result.status, result.answer)
```

自定义模型客户端只需实现 `chat(messages, tools=None, response_format=None)`，返回 assistant 消息字典。事件回调使用 `on_event=callback`。每次 `run()` 的历史独立保存在内存中。

工具参数支持一个明确的 JSON Schema 子集：基本类型、嵌套对象/数组、`required`、`enum`、数值和长度约束；对象不接受额外属性。不支持的 schema 关键字会在注册时拒绝，避免看似校验但实际忽略。

内置工具不会执行任意 Python 表达式或 shell；计算器解析受限 AST，文件读取解析路径后限制在工作目录内。自定义工具是调用者提供的可信同步 Python 代码，**框架不是执行沙箱，也不保证能强制停止阻塞的自定义函数**。取消在模型/工具调用之间检查；需要长时间 I/O 的扩展工具应自行实现超时。

只有显式指定 `--trace` 才保存事件日志，日志包含工具参数和结果。默认不写聊天记录、不遥测；配置为本地地址时模型通信留在本机。改用远程 `host` 后，任务及工具结果会发送到该地址。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `lite_react/` | 核心调度循环、工具注册表、Ollama 适配器、CLI、离线演示 |
| `tests/` | 39 项标准库 unittest：调度、工具、自评、CLI、HTTP 协议 |
| `examples/` | 最小 Agent 与自定义工具示例 |
| `workspace/` | 默认示例文本目录 |
| `config.example.json` | 配置示例；复制为 `config.json` 后使用 |
| `run.py` / `run.sh` | 源码 CLI 入口 |
| `start.bat` / `demo.bat` / `doctor.bat` | Windows 交互启动、离线演示、连接检查 |
| `build-windows.ps1` | 用 PyInstaller 构建 Windows x64 便携包（构建依赖，非运行依赖） |
| `pyproject.toml` | 包元数据与 Python 版本要求，无第三方运行依赖 |
| `licenses/` | Python、PyInstaller 与 WeKnora 上游许可证 |
| `UPSTREAM.md` / `THIRD-PARTY.md` | 上游对应关系与第三方声明 |
| `TEST-RESULTS.md` | 1.0.0 实际验证范围与限制 |
| `CONTRIBUTING.md` / `CHANGELOG.md` | 贡献流程与版本记录 |

`start.bat` / `demo.bat` / `doctor.bat` 会优先使用同目录的便携 EXE；没有 EXE 时回退到本机 Python。源码可在 Windows、macOS、Linux 的 Python 环境运行。重建 EXE 需在 Windows 安装 PyInstaller 6.16.0，执行 `build-windows.ps1`；PyInstaller 只用于构建。

## 来源与验证边界

基于 WeKnora 固定提交 `2fbfb4471581cd5e7d731bc7a2d443fe7d8e95b5` 的核心结构重新实现，保留许可证和源码对应说明。没有把整个 Go 后端打包进来，也不声称与 WeKnora 全功能兼容。

构建机器没有运行中的 Ollama 和本地模型；已验证的是调度器、真实 HTTP 适配器连接测试服务，以及 Windows 便携程序。离线 demo 的模型决策和分数是脚本，真实模型效果取决于接收者的模型与配置。详见 `TEST-RESULTS.md`。

应用源码使用 MIT 许可证，见 [LICENSE](LICENSE)；上游与构建工具声明见 [THIRD-PARTY.md](THIRD-PARTY.md) 和 [UPSTREAM.md](UPSTREAM.md)。
