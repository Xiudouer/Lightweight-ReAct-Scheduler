"""Deterministic mock model: exercises the real loop/tools without an LLM."""

import json


class DemoClient:
    def __init__(self):
        self.step = 0

    def chat(self, messages, tools=None, response_format=None):
        if response_format and "confidence" in response_format.get("properties", {}):
            return dict(role="assistant", content=json.dumps(dict(
                confidence=0.95, needs_more=False, feedback="演示评分，非真实模型评估。"), ensure_ascii=False))
        self.step += 1
        if self.step == 1:
            return dict(role="assistant", content="", tool_calls=[dict(function=dict(
                name="read_file", arguments={"path": "welcome.txt"}))])
        if self.step == 2:
            return dict(role="assistant", content="", tool_calls=[dict(function=dict(
                name="calculate", arguments={"expression": "10000 * (1 + 0.03) ** 5"}))])
        return dict(role="assistant", content=(
            "【离线演示：使用脚本模型，不是真实 Ollama 推理】\n"
            "已读取 welcome.txt 并执行计算工具。10000 元按 3% 年复利，5 年后为 11592.74 元。\n"
            "Think → Act → Observe 已完成两轮工具调用；工具由真实调度器执行。"))
