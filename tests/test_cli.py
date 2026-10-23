"""Run against source, or set LITEREACT_TEST_EXE to test the portable build."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = pathlib.Path(__file__).resolve().parent.parent


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        executable = os.environ.get("LITEREACT_TEST_EXE")
        command = [executable] if executable else [sys.executable, str(ROOT / "run.py")]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        if executable and os.name == "nt":
            # Verify the portable executable without a Python executable on PATH.
            env["PATH"] = str(pathlib.Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32")
        return subprocess.run(command + list(args), capture_output=True, encoding="utf-8",
                              errors="replace", timeout=30, cwd=ROOT, env=env)

    def test_demo_json_and_bundled_runtime(self):
        completed = self.invoke("--demo", "--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual((data["status"], data["rounds"], data["tool_calls"]), ("completed", 3, 2))
        self.assertIn("离线演示", data["answer"])

    def test_demo_can_disable_review(self):
        completed = self.invoke("--demo", "--json", "--no-review")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIsNone(json.loads(completed.stdout)["confidence"])

    def test_missing_config_has_structured_error(self):
        completed = self.invoke("--json", "--config", "this-file-does-not-exist.json", "task")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stderr)["status"], "error")

    def test_real_cli_http_round_trip_with_unicode_workspace(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(request)
                if len(requests) == 1:
                    message = {"role": "assistant", "content": "", "tool_calls": [
                        {"function": {"name": "read_file", "arguments": {"path": "说明.txt"}}}]}
                else:
                    observation = json.loads(request["messages"][-1]["content"])
                    content = json.loads(observation["output"])["content"]
                    message = {"role": "assistant", "content": "读取成功：" + content}
                raw = json.dumps(dict(done=True, done_reason="stop", message=message)).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="中文 空格 ") as temp:
                folder = pathlib.Path(temp)
                (folder / "说明.txt").write_text("本地工具测试成功", encoding="utf-8")
                completed = self.invoke("读取说明文件", "--host", f"http://127.0.0.1:{server.server_port}",
                                        "--workspace", str(folder), "--no-review", "--json")
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["status"], "completed")
                self.assertIn("本地工具测试成功", result["answer"])
                self.assertEqual(len(requests), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
