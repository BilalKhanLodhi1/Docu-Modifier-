# DocuCraft AI

A self-hosted Django application for working with Word and PDF documents. Upload a file, then:

- **Rewrite** it with AI in a professional, corporate, academic, grammar-only, concise or custom style. Numbers, dates, names, citations, links and code are protected, every change is fact-checked, and you approve changes before they are saved.
- **Apply a template** that sets page size, margins, fonts, heading styles, a cover page, a table of contents, headers, footers and page numbers.
- **Edit images** inside a Word document (crop, rotate, brightness, contrast, sharpening, noise removal, resize, replace) and put them back in the same place.
- **Split** a PDF by page ranges, or a Word document by headings or tasks.
- **Convert** Word to PDF, or PDF to editable Word, with OCR for scanned PDFs.
- **Run several steps at once** (rewrite, then template, then PDF export).

Every operation creates a new version. The original upload is never modified, and you can return to any earlier version. Each user's files are private, and every download is checked against the signed-in user.

---

## Quick start on macOS

You do not need XAMPP or Apache. Django runs its own server, so the project can live in any folder.

### 1. Install the system tools (once)

```bash
# Homebrew (skip if installed): https://brew.sh
brew install --cask libreoffice      # Word to PDF, and page numbers on the contents page
brew install tesseract               # OCR for scanned PDFs (optional)
brew install ollama                  # local AI for rewriting
ollama pull qwen2.5:7b               # about 4.7 GB, once
```

Python 3.12 or 3.13 from python.org is recommended. 3.14 should work, but if a package fails to install, use 3.13.

### 2. Set up and run

```bash
cd /path/to/docucraft
bash setup.sh      # creates .venv, installs packages, writes .env, prepares the database
bash run.sh        # starts Ollama if needed and opens the server
```

Open http://127.0.0.1:8000 and create an account. `setup.sh` is safe to run again after every update; it keeps your existing `.env` and data.

### 3. Check everything is working

```bash
source .venv/bin/activate
python manage.py doctor
```

This prints the folder and code version in use, the AI model and limits, and sends a small live request to the AI with timing. It also checks LibreOffice and Tesseract. Anything marked **FIX** comes with the exact command to run. If something goes wrong, send this output.

### AI provider options

**Ollama (recommended, private).** Documents never leave your computer.

```bash
brew install ollama
ollama serve                      # leave this running in its own terminal
ollama pull qwen2.5:7b            # about 4.7 GB
```

The defaults in `.env` already point at Ollama and `qwen2.5:7b`. `OLLAMA_MODEL` must match a name shown by `ollama list` exactly, including the part after the colon. A larger model (for example `qwen2.5:14b`) gives better rewrites if your Mac has 16 GB of memory or more.

Ollama streams its answer, so a long rewrite is never cut off while the model is still writing. A request fails only if the model stays silent for `AI_TIMEOUT` seconds, or runs longer than `AI_MAX_CALL_SECONDS` in total. The first request after starting Ollama is slower because the model has to load into memory.

**Anthropic or OpenAI (cloud).** Set `AI_PROVIDER=anthropic` (or `openai`) and the matching API key in `.env`. Each user must also tick "Allow sending document text to a cloud AI provider" in Settings; without that consent, rewrite jobs refuse to run. Only the text of the sections being rewritten is sent.

Settings in the app shows whether the provider is reachable and which conversion tools were found.

---

## How rewriting protects your content

1. The document is read paragraph by paragraph. Code, paragraphs containing links, images or equations, and short table cells are never sent to the AI.
2. Text is sent in chunks as structured data. The AI is told the text is untrusted, so instructions written inside a document ("ignore previous instructions…") are treated as text to edit, not commands.
3. Each returned section is checked for dropped or altered numbers, dates, names, citations, URLs and emails, for suspicious length changes, and for headings turned into prose.
4. Bold, italic, code-font, superscript and subscript words keep their formatting in the rewritten sentence.
5. Sections that fail are sent back **once**, with a note naming exactly what was lost. If the second attempt still fails, the original wording is kept and the section is marked with the reason.
6. You review a side-by-side comparison with insertions and deletions highlighted, tick the changes you want, and only then is a new version saved.

---

## Templates and the contents page

Applying a template formats the whole document: page size, margins, fonts, heading styles, code blocks, tables (shaded header row that repeats across pages), captions, a cover page, header, footer and page numbers.

The contents page lists Heading 1 to 3, each entry links to its section, and page numbers are measured from a real layout pass using LibreOffice, so they are correct in Word, LibreOffice and exported PDFs. The cover is unnumbered, the contents page uses roman numerals and the body starts at page 1. In Word the contents page also stays a live field, so after editing you can right-click it and choose Update Field.

Formatting a version that was already formatted replaces the earlier cover and contents page instead of adding a second set.

## Running the tests

```bash
python manage.py test apps
```

The suite (56 tests) generates its own sample documents and uses a stand-in AI, so it needs no network or API key. It covers access control between users, upload validation, every job type end to end, the fact-check and retry, template formatting, splitting, image editing, conversion and every page rendering. The LibreOffice and OCR tests are skipped automatically if those tools aren't installed.

---

## Configuration

All settings come from `.env` (see `.env.example` for the full list).

| Setting | Default | Purpose |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Set to `False` in production. A real `DJANGO_SECRET_KEY` is then required. |
| `AI_PROVIDER` | `ollama` | `ollama`, `anthropic`, `openai` or `none`. Users can override it in Settings. |
| `DOCUCRAFT_MAX_UPLOAD_MB` | `25` | Largest accepted upload. |
| `DOCUCRAFT_RETENTION_DAYS` | `30` | Documents untouched for this long are removed by the cleanup command. |
| `DOCUCRAFT_JOB_TIMEOUT` | `600` | A job that reports no progress for twice this long is marked failed. Long jobs that keep progressing are never cut off. |
| `AI_TIMEOUT` | `180` | Seconds the AI may stay silent before a request fails. |
| `AI_MAX_CALL_SECONDS` | `900` | Longest one AI request may run in total. |
| `AI_CHUNK_CHARS` | `3000` | Characters sent per AI request. Lower it on slower computers. |
| `DOCUCRAFT_ASYNC_JOBS` | `True` | Run jobs in the background. `False` runs them during the request (useful for debugging). |
| `LIBREOFFICE_PATH`, `TESSERACT_PATH` | auto-detected | Set only if the tools are installed somewhere unusual. |
| `POSTGRES_*` | unset | Set `POSTGRES_DB` and the others to use PostgreSQL instead of SQLite. |

### Housekeeping

```bash
python manage.py cleanup_documents            # apply the retention policy, clear temp files
python manage.py cleanup_documents --dry-run  # show what would be removed
```

Schedule it once a day with cron or launchd on a server.

---

## Project layout

```
config/                 settings and URL routing
apps/
  core/                 navigation and shared template tags
  accounts/             sign-in, registration, per-user settings and AI consent
  documents/            uploads, versions, job runner, downloads, combined workflow
  rewriting/            AI rewrite setup and review
  templates_manager/    formatting templates (built-in and your own)
  image_tools/          image gallery and editor
  splitting/            split planning and preview
  converters/           Word/PDF conversion
  history/              activity log
services/               document logic with no web code (reader, writer, AI, images, split, convert)
templates/              HTML pages
static/                 CSS, JavaScript and the logo
```

---

## Troubleshooting

**"Word to PDF conversion needs LibreOffice"**: install it with `brew install --cask libreoffice`. If it's installed somewhere else, set `LIBREOFFICE_PATH` to the `soffice` binary.

**"Ollama (local) is not available"**: start `ollama serve` in a separate terminal and check `OLLAMA_MODEL` matches a model you have pulled (`ollama list`).

**"Ollama has no model named …" (HTTP 404)**: `OLLAMA_MODEL` in `.env` doesn't match an installed model. Run `ollama list` and copy the name exactly, then restart the Django server; `.env` is only read at startup.

**"The local model did not start answering / continue within … seconds"**: the model went silent. The first request after starting Ollama includes loading the model, which can take a minute on older Macs. Try again; if it keeps happening, raise `AI_TIMEOUT` (for example to `300`) or close other heavy apps.

**"One part of the document took over 15 minutes"**: the computer is generating slowly. Lower `AI_CHUNK_CHARS` (for example to `1500`) so each request is smaller, or use a smaller model such as `qwen2.5:3b`.

**A rewrite says the AI returned an unreadable response**: small models sometimes break the required JSON format. Try again, lower `AI_CHUNK_CHARS`, or use a larger model.

**Scanned PDF converts to an empty Word file**: install Tesseract and choose "Always use OCR" on the Convert page.

**A job stays on "Working on it" after restarting the server**: background jobs run inside the server process, so a restart stops them. They are marked failed automatically after twice the job timeout; use "Try again" on the job page.

**"database is locked"**: SQLite allows one writer at a time. It's fine for one person; for a team, use PostgreSQL.

**Pages show without styling when `DJANGO_DEBUG=False`**: Django doesn't serve static files in production mode. Run `python manage.py collectstatic` and serve `staticfiles/` with your web server, or add WhiteNoise.

---

## Known limitations

- Background jobs use threads in the web process. That suits one machine and a small team. For production with several worker processes, run `apps.documents.jobs.execute_job` from a task queue such as Celery.
- The in-browser Word preview is simplified (text, headings, tables and images). Exact layout, headers, footers and fonts appear only in the downloaded file.
- Word documents have no fixed pages, so the page count shown for them is an estimate, and Word files split by structure rather than page number.
- PDF to Word conversion rebuilds layout; complex multi-column pages may need manual tidying.
- AI image editing is disabled unless an image provider is configured (`AI_IMAGE_PROVIDER`). All the local adjustments work without it.
- The built-in academic template was built from a written specification because the reference PDF was never supplied. Duplicate it on the Templates page to adjust it.
