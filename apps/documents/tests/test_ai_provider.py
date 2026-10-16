"""Ollama client: streaming, timeouts and error reporting, against a fake Ollama server."""
import json
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from services.ai_provider import OllamaProvider, _context_size
from services.exceptions import AIProviderError

from .base import DocuCraftTestCase


class FakeOllama(BaseHTTPRequestHandler):
    """Behaviour is chosen by the model name in the request."""
    def log_message(self, *args):
        pass

    def do_GET(self):  # /api/tags
        self._json(200, {"models": [{"name": "qwen2.5:7b"}, {"name": "slow:1b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        self.server.last_request = body
        if model == "missing:1b":
            return self._json(404, {"error": f"model '{model}' not found"})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if model == "silent:1b":
            time.sleep(3)
            return
        words = ['{"ok"', ': ', 'true', '}']
        delay = 0.6 if model == "slow:1b" else 0
        for w in words:
            time.sleep(delay)
            self._line({"message": {"content": w}, "done": False})
        if model == "broken:1b":
            return self._line({"error": "model runner crashed"})
        self._line({"message": {"content": ""}, "done": True})

    def _line(self, obj):
        self.wfile.write((json.dumps(obj) + "\n").encode())
        self.wfile.flush()

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class OllamaClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def run_model(self, model, **extra):
        with override_settings(OLLAMA_BASE_URL=self.url, OLLAMA_MODEL=model, AI_TIMEOUT=1, **extra):
            return OllamaProvider().complete("system", "user text")

    def test_slow_but_steady_answer_is_not_cut_off(self):
        start = time.monotonic()
        self.assertEqual(self.run_model("slow:1b"), '{"ok": true}')
        self.assertGreater(time.monotonic() - start, 2, "The answer took longer than AI_TIMEOUT in total")

    def test_silent_model_times_out_with_guidance(self):
        with self.assertRaisesRegex(AIProviderError, "did not continue within 1 seconds"):
            self.run_model("silent:1b")

    def test_overall_cap(self):
        with self.assertRaisesRegex(AIProviderError, "took over"):
            self.run_model("slow:1b", AI_MAX_CALL_SECONDS=1)

    def test_missing_model_names_the_fix(self):
        with self.assertRaisesRegex(AIProviderError, "ollama pull missing:1b"):
            self.run_model("missing:1b")

    def test_error_mid_stream(self):
        with self.assertRaisesRegex(AIProviderError, "model runner crashed"):
            self.run_model("broken:1b")

    def test_request_is_streamed_with_sized_context(self):
        self.run_model("qwen2.5:7b")
        sent = self.server.last_request
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["format"], "json")
        self.assertEqual(sent["options"]["num_ctx"], 4096)

    def test_availability_needs_exact_model(self):
        for model, ok in [("qwen2.5:7b", True), ("qwen2.5:14b", False), ("llama3.1:8b", False)]:
            with override_settings(OLLAMA_BASE_URL=self.url, OLLAMA_MODEL=model):
                self.assertEqual(OllamaProvider().available()[0], ok, model)

    def test_context_size_bounds(self):
        self.assertEqual(_context_size("s", "u"), 4096)
        self.assertEqual(_context_size("s" * 3000, "u" * 9000), 8192)
        self.assertEqual(_context_size("s", "u" * 200000), 16384)


class WatchdogTests(DocuCraftTestCase):
    @override_settings(DOCUCRAFT_JOB_TIMEOUT=60)
    def test_long_job_that_is_still_reporting_progress_survives(self):
        from apps.documents.jobs import _expire_stale_jobs
        from apps.documents.models import ProcessingJob
        doc = self.make_doc()
        old = timezone.now() - timedelta(hours=2)
        busy = ProcessingJob.objects.create(document=doc, user=self.user, operation="rewrite", status="running",
                                            heartbeat_at=timezone.now())
        stuck = ProcessingJob.objects.create(document=doc, user=self.user, operation="rewrite", status="running",
                                             heartbeat_at=old)
        ProcessingJob.objects.filter(pk__in=[busy.pk, stuck.pk]).update(created_at=old)
        _expire_stale_jobs()
        busy.refresh_from_db(); stuck.refresh_from_db()
        self.assertEqual(busy.status, "running")
        self.assertEqual(stuck.status, "failed")
        self.assertIn("stopped reporting progress", stuck.error)
