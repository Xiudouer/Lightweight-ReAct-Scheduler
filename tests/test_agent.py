import json
import pathlib
import tempfile
import threading
import unittest

from lite_react import Agent, AgentConfig, Tool, ToolRegistry, builtin_tools
from lite_react.ollama import ModelError
from lite_react.tools import object_schema


def answer(text):
    return {"role": "assistant", "content": text}


def call(name, arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def review(score=0.9, more=False, feedback="Evidence sufficient"):
    return answer(json.dumps(dict(confidence=score, needs_more=more, feedback=feedback)))


class ScriptedClient:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def chat(self, messages, tools=None, response_format=None):
        self.requests.append(dict(messages=messages, tools=tools, response_format=response_format))
        if not self.responses:
            raise AssertionError("Unexpected model call")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "welcome.txt").write_text("hello local agent\nrate 3%\n", encoding="utf-8")
        self.tools = builtin_tools(self.root)

    def test_native_loop_keeps_assistant_and_tool_pairs(self):
        client = ScriptedClient(call("calculate", {"expression": "(2+3)*7"}), answer("35"), review())
        result = Agent(client, self.tools).run("Calculate precisely")
        self.assertEqual((result.status, result.answer, result.tool_calls), ("completed", "35", 1))
        messages = client.requests[1]["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool"])
        self.assertEqual(messages[-1]["tool_name"], "calculate")
        self.assertEqual(json.loads(json.loads(messages[-1]["content"])["output"])["value"], 35)
        self.assertEqual([e["phase"] for e in result.events],
                         ["think", "act", "observe", "think", "review", "score", "finish"])

    def test_error_is_observed_then_arguments_are_corrected(self):
        client = ScriptedClient(call("calculate", {"expression": "1/0"}),
                                call("calculate", {"expression": "10/2"}), answer("5"))
        result = Agent(client, self.tools, AgentConfig(review=False)).run("Compute")
        self.assertEqual(result.status, "completed")
        obs = [e for e in result.events if e["phase"] == "observe"]
        self.assertFalse(obs[0]["ok"])
        self.assertTrue(obs[1]["ok"])

    def test_confidence_feedback_triggers_refinement(self):
        client = ScriptedClient(answer("Unsupported draft"), review(0.2, True, "Calculate it"),
                                call("calculate", {"expression": "8*9"}), answer("72"), review(0.91))
        result = Agent(client, self.tools).run("What is 8 times 9?")
        self.assertEqual((result.answer, result.refinements, result.confidence), ("72", 1, 0.91))
        self.assertIn("Calculate it", client.requests[2]["messages"][-1]["content"])

    def test_refinement_budget_returns_honest_low_confidence(self):
        client = ScriptedClient(answer("Draft"), review(0.3, True), answer("Still uncertain"), review(0.4))
        result = Agent(client, self.tools, AgentConfig(max_refinements=1)).run("Unknown fact")
        self.assertEqual((result.status, result.confidence), ("low_confidence", 0.4))

    def test_bad_review_does_not_invent_score(self):
        for message in [answer("not json"), review(float("nan")), review(True), review(1.1)]:
            with self.subTest(message=message):
                result = Agent(ScriptedClient(answer("Draft"), message), self.tools).run("task")
                self.assertEqual(result.status, "review_unavailable")
                self.assertIsNone(result.confidence)
                self.assertEqual(result.answer, "Draft")

    def test_identical_calls_stop_before_reexecution(self):
        result = Agent(ScriptedClient(*[call("list_files", {})] * 3), self.tools,
                       AgentConfig(review=False)).run("List files")
        self.assertEqual(result.status, "stalled")
        self.assertEqual(result.tool_calls, 2)

    def test_round_limit_does_not_claim_complete(self):
        result = Agent(ScriptedClient(call("list_files", {})), self.tools,
                       AgentConfig(max_rounds=1)).run("Inspect")
        self.assertEqual(result.status, "max_rounds")

    def test_batch_budget_is_checked_before_side_effects(self):
        hit = []
        registry = ToolRegistry([Tool("touch", "test", object_schema({}, []), lambda: hit.append(True))])
        response = call("touch", {})
        response["tool_calls"] *= 3
        result = Agent(ScriptedClient(response), registry,
                       AgentConfig(max_calls_per_round=2)).run("Do it")
        self.assertEqual(result.status, "tool_limit")
        self.assertEqual(hit, [])

    def test_max_total_tools_checked_before_batch(self):
        response = call("list_files", {})
        response["tool_calls"] *= 2
        result = Agent(ScriptedClient(response), self.tools,
                       AgentConfig(max_tool_calls=1)).run("Inspect")
        self.assertEqual((result.status, result.tool_calls), ("tool_limit", 0))

    def test_three_empty_responses_stop(self):
        result = Agent(ScriptedClient(answer(""), answer(""), answer("")), self.tools).run("task")
        self.assertEqual(result.status, "stalled")

    def test_json_mode_tool_observation_and_finish(self):
        client = ScriptedClient(answer('{"action":"tool","tool":"calculate","arguments":{"expression":"4*4"}}'),
                                answer('{"action":"finish","answer":"16"}'))
        result = Agent(client, self.tools, AgentConfig(mode="json", review=False)).run("Compute")
        self.assertEqual(result.answer, "16")
        self.assertIsNone(client.requests[0]["tools"])
        self.assertIn("Tool observation", client.requests[1]["messages"][-1]["content"])

    def test_json_mode_repairs_malformed_decision(self):
        client = ScriptedClient(answer("bad JSON"), answer('{"action":"finish","answer":"Done"}'))
        result = Agent(client, self.tools, AgentConfig(mode="json", review=False)).run("task")
        self.assertEqual(result.status, "completed")
        self.assertIn("protocol_error", [e["phase"] for e in result.events])

    def test_three_bad_json_decisions_stop(self):
        result = Agent(ScriptedClient(answer("[]"), answer("bad"), answer("{}")), self.tools,
                       AgentConfig(mode="json")).run("task")
        self.assertEqual(result.status, "stalled")

    def test_stringified_arguments_are_validated(self):
        client = ScriptedClient(call("calculate", '{"expression":"6*7"}'), answer("42"))
        result = Agent(client, self.tools, AgentConfig(review=False)).run("task")
        self.assertEqual(result.status, "completed")

    def test_malformed_function_is_an_observation_not_a_crash(self):
        client = ScriptedClient({"content": "", "tool_calls": [{"function": []}]}, answer("Cannot use it"))
        result = Agent(client, self.tools, AgentConfig(review=False)).run("task")
        self.assertEqual(result.status, "completed")
        self.assertFalse([e for e in result.events if e["phase"] == "observe"][0]["ok"])

    def test_cancellation_before_call(self):
        flag = threading.Event()
        flag.set()
        client = ScriptedClient()
        result = Agent(client, self.tools).run("task", cancelled=flag)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(client.requests, [])

    def test_context_budget_fails_without_orphaning_history(self):
        client = ScriptedClient()
        result = Agent(client, self.tools, AgentConfig(max_context_chars=4000)).run("x" * 5000)
        self.assertEqual(result.status, "context_limit")
        self.assertEqual(client.requests, [])

    def test_model_failure_is_structured(self):
        result = Agent(ScriptedClient(ModelError("offline")), self.tools).run("task")
        self.assertEqual((result.status, result.error), ("error", "offline"))

    def test_thinking_is_not_in_events_or_final_result(self):
        msg = call("list_files", {})
        msg["thinking"] = "PRIVATE_MODEL_THINKING"
        client = ScriptedClient(msg, answer("Done"))
        result = Agent(client, self.tools, AgentConfig(review=False)).run("task")
        self.assertNotIn("PRIVATE_MODEL_THINKING", json.dumps(result.to_dict()))
        self.assertEqual(client.requests[1]["messages"][2]["thinking"], "PRIVATE_MODEL_THINKING")

    def test_config_rejects_invalid_budgets(self):
        for params in [dict(max_rounds=0), dict(max_tool_calls=True), dict(min_confidence=float("nan")),
                       dict(max_refinements=-1), dict(mode="unknown")]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                AgentConfig(**params)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "notes.txt").write_text("第一行\n年利率 3%\n第三行\n", encoding="utf-8")
        self.tools = builtin_tools(self.root)

    def test_calculator_and_no_python_execution(self):
        for expression, expected in [("10000*(1+0.03)**5", 11592.740743), ("-3+8//2", 1)]:
            result = self.tools.execute("calculate", dict(expression=expression))
            self.assertTrue(result["ok"])
            self.assertAlmostEqual(json.loads(result["output"])["value"], expected)
        for expression in ["__import__('os').getcwd()", "2**1000000", "float('inf')", "(1+2j)"]:
            self.assertFalse(self.tools.execute("calculate", dict(expression=expression))["ok"])

    def test_validation_happens_before_handler(self):
        calls = []
        registry = ToolRegistry([Tool("count", "test", object_schema({"n": {"type": "integer"}}, ["n"]),
                                      lambda n: calls.append(n))])
        for args in [{}, {"n": True}, {"n": 1, "extra": "value"}, "bad"]:
            self.assertFalse(registry.execute("count", args)["ok"])
        self.assertEqual(calls, [])

    def test_unknown_tool_and_exception_are_observed(self):
        self.assertFalse(self.tools.execute("shell", {})["ok"])
        self.assertFalse(self.tools.execute("calculate", {"expression": "1/0"})["ok"])

    def test_duplicate_and_unsupported_schema_rejected(self):
        with self.assertRaises(ValueError):
            self.tools.add(Tool("calculate", "duplicate", object_schema({}, []), lambda: None))
        with self.assertRaises(ValueError):
            self.tools.add(Tool("unknown", "schema", {"type": "object", "$ref": "missing"}, lambda: None))

    def test_path_traversal_and_absolute_escape(self):
        self.assertFalse(self.tools.execute("read_file", {"path": "../outside.txt"})["ok"])
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_text("secret", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.assertFalse(self.tools.execute("read_file", {"path": str(outside)})["ok"])

    def test_symlink_escape(self):
        outside = self.root.parent / (self.root.name + "-target.txt")
        outside.write_text("secret", encoding="utf-8")
        self.addCleanup(outside.unlink)
        try:
            (self.root / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("OS does not allow symlink creation")
        self.assertFalse(self.tools.execute("read_file", {"path": "link.txt"})["ok"])

    def test_read_page_search_and_list(self):
        value = self.tools.execute("read_file", {"path": "notes.txt", "start_line": 2, "max_lines": 1})
        output = json.loads(value["output"])
        self.assertEqual(output["content"], "2: 年利率 3%")
        self.assertTrue(output["truncated"])
        hits = json.loads(self.tools.execute("search_files", {"query": "利率"})["output"])
        self.assertEqual(hits["matches"][0]["line"], 2)
        self.assertEqual(json.loads(self.tools.execute("list_files", {})["output"])["files"], ["notes.txt"])

    def test_observation_truncation_is_explicit(self):
        tools = ToolRegistry([Tool("long", "long text", object_schema({}, []), lambda: "x" * 500)])
        result = tools.execute("long", {}, max_chars=100)
        self.assertTrue(result["truncated"])
        self.assertEqual((len(result["output"]), result["original_chars"]), (100, 500))

    def test_large_utf8_read_not_broken_by_byte_boundary(self):
        (self.root / "large.txt").write_text("中" * 100000, encoding="utf-8")
        result = self.tools.execute("read_file", {"path": "large.txt"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
