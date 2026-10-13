"""Helpers for safe, user-separated file paths under MEDIA_ROOT."""
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path


def user_subdir(user_id, kind):
    """Relative storage folder, e.g. 'processed/user_7/2026/10'."""
    from datetime import date
    today = date.today()
    return f"{kind}/user_{int(user_id)}/{today:%Y/%m}"


def internal_name(suffix):
    suffix = suffix if suffix.startswith(".") else "." + suffix
    return f"{uuid.uuid4().hex}{suffix.lower()}"


@contextmanager
def temp_workdir(prefix="docucraft_"):
    """A private temp directory that is always removed afterwards."""
    from django.conf import settings
    base = Path(settings.MEDIA_ROOT) / "temporary"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
