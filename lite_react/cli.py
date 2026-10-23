import argparse
import json
import pathlib
import sys
from dataclasses import fields

from . import __version__
from .core import Agent, AgentConfig
from .demo import DemoClient
from .ollama import ModelError, OllamaClient
from .tools import builtin_tools


def app_dir():
    return pathlib.Path(sys.executable).parent if getattr(sys, "frozen", False) else pathlib.Path(__file__).resolve().parent.parent


def parser():
    p = argparse.ArgumentParser(description="LiteReAct — 本地 Think → Act → Observe 调度器")
    p.add_argument("task", nargs="?", help="任务；省略时进入交互模式")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=pathlib.Path, help="JSON 配置路径，默认程序旁的 config.json")
    p.add_argument("--model", help="Ollama 模型名称")
    p.add_argument("--host", help="Ollama 地址")
    p.add_argument("--workspace", type=pathlib.Path, help="文件工具可读取的目录")
    p.add_argument("--mode", choices=("native", "json"), help="原生工具调用，或结构化 JSON 决策")
    p.add_argument("--max-rounds", type=int)
    p.add_argument("--no-review", action="store_true", help="关闭模型自评与再迭代")
    p.add_argument("--demo", action="store_true", help="无需模型的脚本演示（不代表模型推理）")
    p.add_argument("--doctor", action="store_true", help="检查 Ollama 连接和已安装的模型")
    p.add_argument("--json", action="store_true", help="将最终结果和事件输出为 JSON")
    p.add_argument("--trace", type=pathlib.Path, help="可选：保存事件 JSONL（含工具参数及结果）")
    return p


def load_config(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {f.name for f in fields(AgentConfig)} | {"model", "host", "workspace", "timeout", "temperature", "num_ctx", "num_predict", "retries"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("配置必须是 JSON 对象，且只包含 README 列出的字段")
    return data


LABELS = {"think": "Think · 决策", "act": "Act · 调用工具", "observe": "Observe · 工具反馈",
          "review": "Review · 检查答案", "score": "Score · 模型自评", "refine": "Refine · 再迭代",
          "protocol_error": "修正 JSON", "finish": "结束"}
STATUS = {"completed": "完成", "low_confidence": "未通过自评的草稿", "review_unavailable": "自评不可用，返回草稿",
          "max_rounds": "达到轮数上限", "tool_limit": "达到工具预算", "stalled": "无进展，已停止",
          "context_limit": "达到上下文预算", "cancelled": "已取消", "error": "执行失败"}


def main(argv=None):
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    trace_handle = None
    try:
        config_path = (args.config or app_dir() / "config.json").resolve()
        if args.config and not config_path.is_file():
            raise ValueError(f"找不到配置文件：{config_path}")
        settings = load_config(config_path)
        agent_settings = {f.name: settings[f.name] for f in fields(AgentConfig) if f.name in settings}
        for name, value in (("mode", args.mode), ("max_rounds", args.max_rounds)):
            if value is not None:
                agent_settings[name] = value
        if args.no_review:
            agent_settings["review"] = False
        if args.demo:
            agent_settings["mode"] = "native"
        cfg = AgentConfig(**agent_settings)
        workspace = (args.workspace.resolve() if args.workspace else
                     (config_path.parent / settings.get("workspace", "workspace")).resolve())
        if args.demo:
            workspace = app_dir() / "workspace"
        model = args.model or settings.get("model", "qwen3:4b")
        host = args.host or settings.get("host", "http://127.0.0.1:11434")
        client_options = {key: settings[key] for key in
                          ("timeout", "temperature", "num_ctx", "num_predict", "retries") if key in settings}
        client = OllamaClient(model=model, host=host, **client_options)
        if args.doctor:
            try:
                models = client.models()
                found = model in models or model + ":latest" in models
                info = dict(connected=True, host=host, configured_model=model, model_installed=found, models=models)
                print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else
                      f"Ollama 已连接：{host}\n已安装模型：{', '.join(models) or '(无)'}\n配置模型 {model}：{'可用' if found else '未安装'}")
                return 0 if found else 1
            except ModelError as exc:
                info = dict(connected=False, host=host, error=str(exc))
                print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else
                      f"Ollama 未连接：{exc}\n请启动 Ollama，并运行 ollama pull {model}")
                return 1
        tools = builtin_tools(workspace)
        if args.trace:
            trace_handle = args.trace.open("a", encoding="utf-8")

        def event(event):
            if trace_handle:
                trace_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                trace_handle.flush()
            if args.json or event["phase"] == "finish":
                return
            phase = event["phase"]
            detail = event.get("tool", "")
            if phase == "observe":
                detail += " · " + ("成功" if event.get("ok") else event.get("error", "失败"))
            if phase == "score":
                detail = f"{event['confidence']:.2f}（非准确率保证）"
            print(f"[{event['round']}] {LABELS.get(phase, phase)} {detail}", file=sys.stderr, flush=True)

        def run(task):
            active_client = DemoClient() if args.demo else client
            result = Agent(active_client, tools, cfg, on_event=event).run(task)
            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            else:
                print("\n" + (result.answer or "未得到完整答案。"))
                print(f"\n状态：{STATUS.get(result.status, result.status)} | 轮数 {result.rounds} | 工具调用 {result.tool_calls}")
                if result.error:
                    print("说明：" + result.error)
            return 0 if result.status == "completed" else 2

        if args.demo:
            return run("读取 welcome.txt，并用工具计算 10000 元按 3% 年复利 5 年后的金额。")
        if args.task:
            return run(args.task)
        if args.json:
            raise ValueError("--json 需要提供任务，或与 --demo / --doctor 搭配")
        print(f"LiteReAct {__version__}\n模型：{model}\n工作目录：{workspace}\n"
              "每条任务独立运行；输入 /exit 退出。Ctrl+C 可中断当前任务。")
        try:
            models = client.models()
        except ModelError as exc:
            print(f"\n{exc}\n请先启动 Ollama，再运行 ollama pull {model}\n也可以双击 demo.bat 体验离线演示。")
            return 1
        if model not in models and model + ":latest" not in models:
            if not models:
                print(f"尚无已安装模型。请先运行：ollama pull {model}")
                return 1
            print("配置的模型未安装，可选择已有模型：")
            for number, name in enumerate(models, 1):
                print(f"  {number}. {name}")
            choice = input("模型序号（回车退出）：").strip()
            if not choice:
                return 0
            if not choice.isdecimal() or not 1 <= int(choice) <= len(models):
                raise ValueError("模型序号无效")
            client.model = models[int(choice) - 1]
            print(f"本次使用 {client.model}。若模型不支持原生工具，请将 config.json 的 mode 改成 json。")
        while True:
            try:
                task = input("\n任务 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if task.lower() in ("/exit", "/quit"):
                return 0
            if task:
                run(task)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps(dict(status="error", error=str(exc)), ensure_ascii=False) if args.json
              else f"配置或文件错误：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if trace_handle:
            trace_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
