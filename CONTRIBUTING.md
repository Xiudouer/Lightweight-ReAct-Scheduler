# Contributing

感谢你改进 LiteReAct。这个项目刻意保持小而可审计：**Python 标准库、单机运行、只连接用户配置的 Ollama 地址**。新增功能应优先符合这个范围。

## 开发环境

- Python 3.10+
- 可选：本地 Ollama 与支持工具调用的模型（测试不要求）
- 不需要 `pip install`；源码没有第三方运行依赖

```sh
python run.py --demo
python -m unittest discover -s tests -v
```

测试使用本地测试 HTTP 服务，不访问公网、不调用真实模型。

## 修改准则

- 保持依赖为零。引入第三方运行依赖前先开 Issue 讨论，并说明离线、许可和安全影响。
- 不要为了便利加入 `eval`、任意 `exec`、shell 拼接或不受限的文件路径。内置工具必须继续限制在 `workspace` 内。
- 修改调度、预算、重试、工具参数校验或错误处理时，必须补充或更新 `tests/` 中的测试。
- 保持模型调用与工具执行可取消；不要在模型 HTTP 重试时自动重放有副作用的工具。
- 更新用户可见行为时同步修改 README、`config.example.json`（如适用）和 `CHANGELOG.md`。
- 不要提交 `config.json`、个人 `workspace/` 内容、trace 日志、EXE、`runtime/`、发布 ZIP 或任何凭据。这些路径已在 `.gitignore` 中排除。

## 提交与 Pull Request

1. 从最新 `main` 创建分支。
2. 一个提交只做一类改动，提交信息说明“为什么”。
3. 在 PR 中写清：行为变化、测试方式、是否影响安全边界。
4. 确保 `python -m unittest discover -s tests -v` 通过；如果跳过测试，请说明原因。
5. 确认没有引入个人路径、令牌、模型文件或构建产物。

## 安全报告

请不要在公开 Issue 中粘贴可利用细节、真实凭据或用户数据。先通过仓库的私密安全报告渠道联系维护者；如果该渠道不可用，请只发一个不含敏感内容的最小说明，等待后续沟通。

## 许可证

提交即表示你同意以本仓库的 MIT 许可证（见 [LICENSE](LICENSE)）发布你的贡献。
