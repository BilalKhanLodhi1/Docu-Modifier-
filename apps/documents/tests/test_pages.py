"""Every page renders, before and after work has been done (catches template errors)."""
import json

from .base import DocuCraftTestCase, FakeAI


class PageTests(DocuCraftTestCase):
    def test_every_page_renders(self):
        from django.test import Client
        for url in ["/accounts/login/", "/accounts/register/"]:
            self.assertEqual(Client().get(url).status_code, 200, url)
        d = self.make_doc()
        p = self.make_doc("five.pdf")
        empty_pages = ["/", "/workspace/", "/rewrite/", "/templates/", "/images/", "/split/", "/convert/", "/history/",
                       "/accounts/settings/"]
        for url in empty_pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)

        with self.fake_ai(FakeAI()):
            self.client.post("/rewrite/", {"document": d.pk, "mode": "professional"})
        rewrite = self.last_job()
        self.client.post("/convert/", {"document": p.pk, "ocr": "off"})
        self.client.post(f"/images/{d.pk}/0/apply/", {"ops": json.dumps({"contrast": 1.1})})
        r = self.client.post("/split/", {"document": d.pk, "method": "heading", "heading_level": "1"})
        split_preview = r["Location"]

        v = d.current_version
        pages = empty_pages + [
            f"/documents/{d.pk}/", f"/documents/{p.pk}/", f"/documents/{d.pk}/preview/{v.pk}/",
            f"/documents/{p.pk}/preview/{p.versions.get(version_number=1).pk}/", f"/rewrite/review/{rewrite.pk}/",
            f"/rewrite/review/{rewrite.pk}/?show=all", f"/jobs/{rewrite.pk}/", "/templates/new/", "/templates/new/?from=1",
            f"/templates/apply/{d.pk}/", f"/images/{d.pk}/", f"/images/{d.pk}/0/", split_preview, "/workspace/?q=lab&type=docx",
            "/history/?status=failed", f"/rewrite/?document={d.pk}", f"/split/?document={p.pk}", f"/convert/?document={p.pk}",
        ]
        for url in pages:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} returned {resp.status_code}")

    def test_job_status_json(self):
        d = self.make_doc()
        self.client.post(f"/templates/apply/{d.pk}/", {"template": 1, "scope": "all", "title": "T"})
        data = self.client.get(f"/jobs/{self.last_job().pk}/status/").json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["progress"], 100)
