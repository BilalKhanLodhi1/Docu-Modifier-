"""python manage.py doctor: check that DocuCraft is installed and configured correctly."""
import platform
import sys
import time
from pathlib import Path

import django
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check the installation, settings, AI model and conversion tools, and report problems in plain words."

    def add_arguments(self, parser):
        parser.add_argument("--no-ai", action="store_true", help="Skip the live AI test request.")

    def handle(self, *args, **opts):
        self.problems = 0
        base = Path(settings.BASE_DIR)
        self.section("Installation")
        self.info("Project folder", base)
        self.info("Python", f"{platform.python_version()} ({sys.executable})")
        self.info("Django", django.get_version())
        self.verify(len(list((base / "templates").rglob("*.html"))) >= 30, "Interface files",
                   f"{len(list((base / 'templates').rglob('*.html')))} pages found",
                   "The templates folder is incomplete. Unzip the full DocuCraft download over this folder.")
        self.verify((base / "apps" / "documents" / "migrations" / "0002_job_heartbeat.py").exists(), "Code version",
                   "current", "This folder has old code. Unzip the latest DocuCraft download over it.")
        self.verify((base / ".env").exists(), ".env file", "found",
                   "No .env file. Run ./setup.sh, or: cp .env.example .env")

        self.section("Database")
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        pending = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
        self.verify(not pending, "Migrations", "up to date", f"{len(pending)} pending. Run: python manage.py migrate")
        if not pending:
            from apps.templates_manager.models import DocumentTemplate
            n = DocumentTemplate.objects.filter(owner__isnull=True).count()
            self.verify(n >= 1, "Built-in templates", f"{n} installed", "Missing. Run: python manage.py migrate")

        self.section("AI rewriting")
        from services.ai_provider import get_provider
        provider = get_provider()
        self.info("Provider", provider.label)
        self.info("Model", getattr(provider, "model", "") or "(none)")
        self.info("Limits", f"silence {settings.AI_TIMEOUT}s, per request {settings.AI_MAX_CALL_SECONDS}s, "
                            f"{settings.AI_CHUNK_CHARS} characters per request")
        if settings.AI_CHUNK_CHARS > 4000 and provider.name == "ollama":
            self.warn("AI_CHUNK_CHARS is high for a local model. Set AI_CHUNK_CHARS=3000 in .env.")
        ok, msg = provider.available()
        self.verify(ok, "Connection", msg, msg)
        if ok and not opts["no_ai"]:
            self.stdout.write("  Sending a small test request (the first one also loads the model)...")
            start = time.monotonic()
            try:
                reply = provider.complete('Reply with JSON only.', 'Return exactly {"ok": true}')
                took = time.monotonic() - start
                self.verify('"ok"' in reply.replace(" ", ""), "Live test", f"answered in {took:.1f}s",
                           f"answered in {took:.1f}s but not in the expected format: {reply[:120]}")
                if took > 60:
                    self.warn("This computer is slow with this model. Lower AI_CHUNK_CHARS to 1500 or use a smaller model.")
            except Exception as exc:
                self.verify(False, "Live test", "", str(exc))

        self.section("Conversion tools")
        from services.conversion_service import dependency_status
        labels = {"libreoffice": "LibreOffice (Word to PDF, contents page numbers)", "pdf2docx": "pdf2docx (PDF to Word)",
                  "tesseract": "Tesseract (OCR for scanned PDFs)", "rembg": "rembg (background removal)"}
        for name, (ok, detail) in dependency_status().items():
            if ok:
                self.ok(labels.get(name, name), "ready")
            elif name in ("tesseract", "rembg"):
                self.warn(f"{labels.get(name, name)}: optional, not installed. {detail}")
            else:
                self.verify(False, labels.get(name, name), "", detail)

        self.stdout.write("")
        if self.problems:
            self.stdout.write(self.style.ERROR(f"{self.problems} problem(s) found. Fix the items marked FIX above."))
        else:
            self.stdout.write(self.style.SUCCESS("Everything needed is working."))

    # output helpers --------------------------------------------------------
    def section(self, title):
        self.stdout.write("\n" + self.style.MIGRATE_HEADING(title))

    def info(self, label, value):
        self.stdout.write(f"  {label}: {value}")

    def ok(self, label, detail):
        self.stdout.write(self.style.SUCCESS("  OK   ") + f"{label}: {detail}")

    def warn(self, text):
        self.stdout.write(self.style.WARNING("  NOTE ") + text)

    def verify(self, condition, label, good, bad):
        if condition:
            self.ok(label, good)
        else:
            self.problems += 1
            self.stdout.write(self.style.ERROR("  FIX  ") + f"{label}: {bad}")
        return condition
