from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.documents.models import Document

from .base import DocuCraftTestCase


class AccessTests(DocuCraftTestCase):
    def test_pages_require_login(self):
        anon = Client()
        for url in ["/", "/workspace/", "/rewrite/", "/images/", "/split/", "/convert/", "/templates/", "/history/"]:
            resp = anon.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/accounts/login/", resp["Location"])

    def test_other_users_cannot_reach_documents_files_or_jobs(self):
        doc = self.make_doc()
        self.client.post(f"/templates/apply/{doc.pk}/", {"template": 1, "scope": "all", "title": "T"})
        job = self.last_job()
        version = doc.current_version
        bob = User.objects.create_user("bob", "bob@example.com", self.password)
        other = Client()
        other.login(username="bob", password=self.password)
        for url in [f"/documents/{doc.pk}/", f"/documents/{doc.pk}/original/", f"/files/version/{version.pk}/",
                    f"/documents/{doc.pk}/preview/{version.pk}/", f"/jobs/{job.pk}/", f"/jobs/{job.pk}/status/",
                    f"/images/{doc.pk}/", f"/templates/apply/{doc.pk}/"]:
            self.assertEqual(other.get(url).status_code, 404, url)
        self.assertEqual(other.post(f"/documents/{doc.pk}/delete/").status_code, 404)
        self.assertContains(other.get(f"/documents/{doc.pk}/"), "isn't available", status_code=404)
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())

    def test_downloads_are_private_and_not_cached(self):
        doc = self.make_doc()
        resp = self.client.get(f"/files/version/{doc.current_version.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_word_preview_blocks_scripts(self):
        doc = self.make_doc()
        resp = self.client.get(f"/documents/{doc.pk}/preview/{doc.current_version.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("default-src 'none'", resp["Content-Security-Policy"])
        self.assertEqual(resp["X-Frame-Options"], "SAMEORIGIN")


class UploadValidationTests(DocuCraftTestCase):
    def post(self, name, data):
        return self.client.post("/documents/upload/", {"file": SimpleUploadedFile(name, data)},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_rejects_unsupported_extension(self):
        resp = self.post("notes.txt", b"hello")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Only .docx and .pdf", resp.json()["error"])

    def test_rejects_renamed_file(self):
        resp = self.post("fake.pdf", b"PK\x03\x04 not really a pdf")
        self.assertEqual(resp.status_code, 400)
        resp = self.post("fake.docx", b"%PDF-1.4 actually a pdf")
        self.assertEqual(resp.status_code, 400)

    def test_rejects_empty_file(self):
        resp = self.post("empty.pdf", b"")
        self.assertEqual(resp.status_code, 400)

    def test_stored_name_is_not_the_user_filename(self):
        resp = self.upload("lab.docx", as_name="../../etc/passwd.docx")
        self.assertEqual(resp.status_code, 200)
        doc = Document.objects.latest("pk")
        self.assertNotIn("..", doc.original_filename)
        self.assertNotIn("passwd", doc.original_file.name)
        self.assertIn(f"user_{self.user.pk}", doc.original_file.name)

    def test_upload_creates_untouched_version_one(self):
        doc = self.make_doc()
        v1 = doc.versions.get(version_number=1)
        self.assertEqual(v1.operation, "upload")
        self.assertTrue(v1.is_current)
        self.assertEqual(doc.inspection["type"], "docx")
        self.assertGreater(doc.inspection["word_count"], 50)


class AccountTests(DocuCraftTestCase):
    def test_register_and_sign_in(self):
        anon = Client()
        resp = anon.post("/accounts/register/", {"username": "carol", "email": "carol@example.com",
                                                  "password1": self.password, "password2": self.password})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(anon.get("/").status_code, 200)

    def test_duplicate_email_rejected(self):
        resp = Client().post("/accounts/register/", {"username": "alice2", "email": "ALICE@example.com",
                                                      "password1": self.password, "password2": self.password})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "already exists")

    def test_logout_requires_post(self):
        self.assertEqual(self.client.post("/accounts/logout/").status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)
