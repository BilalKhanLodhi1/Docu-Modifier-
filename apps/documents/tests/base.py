"""Shared setup: an isolated media folder, synchronous jobs and a predictable AI."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from services.ai_provider import AIProvider

from . import fixtures


class FakeAI(AIProvider):
    """Capitalises the first letter and fixes two known typos. `drop` removes a word to trip the fact check."""
    name = "fake"
    label = "Test AI"

    def __init__(self, drop=None, fix_on_retry=False):
        self.drop = drop
        self.fix_on_retry = fix_on_retry
        self.calls = []

    def available(self):
        return True, "ready"

    def complete(self, system, user, json_mode=True):
        self.calls.append((system, user))
        body = user.split("(data, not instructions):\n", 1)[1]
        payload, _ = json.JSONDecoder().raw_decode(body)
        is_retry = "was rejected" in user
        out = []
        for s in payload["sections"]:
            t = s["text"]
            t = (t[:1].upper() + t[1:]).replace("reuseable", "reusable").replace("store balance", "stores a balance")
            if self.drop and self.drop in t and not (is_retry and self.fix_on_retry):
                t = t.replace(self.drop, "").replace("  ", " ")
            out.append({"id": s["id"], "text": t, "flag": ""})
        return json.dumps({"sections": out})


class DocuCraftTestCase(TestCase):
    password = "Str0ng-pass-123"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix="docucraft_test_")
        cls._override = override_settings(MEDIA_ROOT=cls._media, DOCUCRAFT_ASYNC_JOBS=False, AI_PROVIDER="none")
        cls._override.enable()
        cls.fx = Path(cls._media) / "_fixtures"
        cls.fx.mkdir()
        fixtures.lab_report_docx(cls.fx / "lab.docx")
        fixtures.simple_pdf(cls.fx / "five.pdf", pages=5)
        fixtures.scanned_pdf(cls.fx / "scan.pdf")

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", self.password)
        self.client.login(username="alice", password=self.password)

    # -- helpers ---------------------------------------------------------
    def upload(self, name, client=None, as_name=None):
        data = (self.fx / name).read_bytes()
        f = SimpleUploadedFile(as_name or name, data)
        resp = (client or self.client).post("/documents/upload/", {"file": f}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        return resp

    def make_doc(self, name="lab.docx"):
        from apps.documents.models import Document
        resp = self.upload(name)
        self.assertEqual(resp.status_code, 200, resp.content)
        return Document.objects.filter(owner=self.user).latest("pk")

    def last_job(self):
        from apps.documents.models import ProcessingJob
        return ProcessingJob.objects.latest("pk")

    def fake_ai(self, provider):
        return mock.patch("apps.rewriting.tasks.get_provider", lambda *a, **k: provider)
