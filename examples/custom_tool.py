"""Run from the package root: python -m examples.custom_tool"""
from lite_react import Agent, AgentConfig, OllamaClient, builtin_tools
from pathlib import Path

tools = builtin_tools(Path(__file__).resolve().parent / "workspace")


@tools.register("convert_temperature", "Convert Celsius to Fahrenheit.", {
    "type": "object", "properties": {"celsius": {"type": "number", "minimum": -273.15, "maximum": 10000}},
    "required": ["celsius"], "additionalProperties": False,
})
def convert_temperature(celsius):
    return {"fahrenheit": celsius * 9 / 5 + 32}


if __name__ == "__main__":
    result = Agent(OllamaClient("qwen3:4b"), tools, AgentConfig(review=False)).run("用工具把 25 摄氏度转成华氏度")
    print(result.answer)
