# Changelog

本项目的显著变更记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.0] - 2026-10-19

### Added

- 完整的 Python 源码：`Agent` 调度循环、工具注册表、Ollama HTTP 适配器、CLI 和离线演示。
- Think → Act → Observe 循环，包含轮次、工具调用、重复调用和上下文预算限制。
- 可选的自评与再迭代（`confidence` / `needs_more` / `feedback`），可关闭。
- `native` 与 `json` 两种 Ollama 工具调用模式。
- 只读文本工具与受限 AST 计算器；文件工具限制在指定工作目录。
- 39 项标准库 `unittest` 测试，覆盖调度、工具、自评、CLI 和 HTTP 协议。
- `examples/basic_agent.py`、`examples/custom_tool.py` 与示例 workspace。
- Windows 构建脚本、交互入口和 PyInstaller 便携包构建说明。
- `UPSTREAM.md`、`THIRD-PARTY.md` 与 WeKnora 上游对应关系。

### Verified

- Windows x64 / CPython 3.12.14：`Ran 39 tests`，38 项通过，1 项因符号链接权限跳过。
- Windows 便携程序 4 项命令行测试通过；未在构建机验证真实 Ollama 模型质量或 macOS/Linux 运行。

### Notes

- 1.0.0 为本地 POC/学习实现，不是生产级 Agent 平台或独立安全审计。
- Windows EXE、`runtime/`、模型权重和离线发布 ZIP 不包含在此源码仓库。
