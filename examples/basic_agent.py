"""Run within the complete LiteReAct project: python -m examples.basic_agent "Calculate 42*17"."""
import argparse
import json
from pathlib import Path

from lite_react import Agent, AgentConfig, OllamaClient, builtin_tools


def main():
    parser = argparse.ArgumentParser(description="Minimal local LiteReAct example")
    parser.add_argument("task", help="Task for the local agent")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parent / "workspace"
    agent = Agent(OllamaClient(args.model, host=args.host), builtin_tools(workspace),
                  AgentConfig(review=False))
    result = agent.run(args.task)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
