import json
import pathlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lite_react import Agent, AgentConfig, OllamaClient, builtin_tools
from lite_react.ollama import ModelError


class OllamaHTTPTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.responses = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"models":[{"name":"test:latest"}]}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, body))
                status, payload = owner.responses.pop(0)
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = OllamaClient("test", host=f"http://127.0.0.1:{self.server.server_port}", retries=0, timeout=2)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def message(self, content="", calls=None, done=True, reason="stop"):
        message = dict(role="assistant", content=content)
        if calls:
            message["tool_calls"] = calls
        return 200, dict(done=done, done_reason=reason, message=message)

    def test_http_adapter_end_to_end_tool_then_answer_and_review(self):
        self.responses = [self.message(calls=[{"function": {"name": "calculate", "arguments": {"expression": "6*7"}}}]),
                          self.message("42"), self.message('{"confidence":0.9,"needs_more":false,"feedback":"Verified"}')]
        with tempfile.TemporaryDirectory() as root:
            result = Agent(self.client, builtin_tools(root)).run("Calculate 6*7")
        self.assertEqual((result.answer, result.status, result.confidence), ("42", "completed", 0.9))
        self.assertEqual(len(self.requests), 3)
        path, request = self.requests[0]
        self.assertEqual(path, "/api/chat")
        self.assertFalse(request["stream"])
        self.assertEqual(request["model"], "test")
        self.assertTrue(request["tools"])
        self.assertEqual(self.requests[1][1]["messages"][-1]["role"], "tool")
        self.assertIn("format", self.requests[2][1])
        self.assertNotIn("tools", self.requests[2][1])

    def test_lists_models(self):
        self.assertEqual(self.client.models(), ["test:latest"])

    def test_retries_transient_model_http_error(self):
        self.client.retries = 1
        self.responses = [(503, {"error": "busy"}), self.message("Recovered")]
        self.assertEqual(self.client.chat([dict(role="user", content="task")])["content"], "Recovered")
        self.assertEqual(len(self.requests), 2)

    def test_bad_request_not_retried(self):
        self.client.retries = 2
        self.responses = [(400, {"error": "model does not support tools"})]
        with self.assertRaises(ModelError):
            self.client.chat([])
        self.assertEqual(len(self.requests), 1)

    def test_rejects_truncated_or_invalid_response_before_tools(self):
        for response in [self.message(done=False), self.message(reason="length"), (200, b"not JSON"),
                         (200, {"done": True, "message": []})]:
            with self.subTest(response=response):
                self.responses = [response]
                with self.assertRaises(ModelError):
                    self.client.chat([])

    def test_origin_validation(self):
        for host in ["ftp://localhost", "http://user:password@localhost", "http://localhost/api", "http://localhost?x=1"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                OllamaClient(host=host)


if __name__ == "__main__":
    unittest.main()
