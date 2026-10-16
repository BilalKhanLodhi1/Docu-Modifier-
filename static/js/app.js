/* DocuCraft AI — progressive enhancement only. Every page works without JS. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function csrf(form) {
    const el = form ? form.querySelector("input[name=csrfmiddlewaretoken]") : $("input[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  /* ---------------------------------------------------------- confirmations */
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  $$("select[data-autosubmit]").forEach((sel) => sel.addEventListener("change", () => sel.form.submit()));

  /* ---------------------------------------------------------- uploads */
  $$("form[data-upload]").forEach((form) => {
    const input = $("input[type=file]", form);
    const zone = $(".dropzone", form);
    const status = $(".upload-status", form);

    ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, () => zone.classList.add("is-over")));
    ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, () => zone.classList.remove("is-over")));

    input.addEventListener("change", () => {
      if (!input.files.length) return;
      const file = input.files[0];
      const data = new FormData(form);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      zone.classList.add("is-busy");
      status.classList.remove("is-error");
      status.textContent = `Uploading ${file.name}…`;
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          status.textContent = pct < 100 ? `Uploading ${file.name}: ${pct}%` : `Checking ${file.name}…`;
        }
      });
      xhr.addEventListener("load", () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (_) { /* non-JSON error page */ }
        if (xhr.status === 200 && body.ok) {
          status.textContent = `Uploaded ${body.name}. Opening it…`;
          window.location.href = body.url;
        } else {
          zone.classList.remove("is-busy");
          status.classList.add("is-error");
          status.textContent = body.error || "The upload failed. Check the file and try again.";
          input.value = "";
        }
      });
      xhr.addEventListener("error", () => {
        zone.classList.remove("is-busy");
        status.classList.add("is-error");
        status.textContent = "The upload was interrupted. Check your connection and try again.";
      });
      xhr.send(data);
    });
  });

  /* ---------------------------------------------------------- job progress */
  const jobEl = $("[data-job]");
  if (jobEl) {
    const stageOrder = $$("[data-stage]", jobEl).map((li) => li.dataset.stage);
    const meter = $(".meter", jobEl);
    const bar = $(".meter > span", jobEl);
    const msg = $("[data-job-message]", jobEl);
    const badge = $("[data-job-badge]", jobEl);

    function paint(state) {
      const pct = state.status === "completed" ? 100 : state.progress;
      bar.style.width = pct + "%";
      meter.setAttribute("aria-valuenow", pct);
      const at = stageOrder.indexOf(state.stage);
      $$("[data-stage]", jobEl).forEach((li, i) => {
        const done = state.status === "completed" || (at >= 0 && i < at);
        li.classList.toggle("is-done", done);
        li.classList.toggle("is-active", state.status === "running" && i === at);
      });
      const text = state.status === "failed" ? state.error : state.message;
      if (text && msg.textContent !== text) msg.textContent = text;
    }

    const initial = jobEl.dataset.status;
    paint({ status: initial, stage: initial === "completed" ? "completed" : "", progress: parseInt(bar.style.width, 10) || 0, message: msg.textContent });

    if (initial === "queued" || initial === "running") {
      let delay = 1000;
      const poll = () => {
        fetch(jobEl.dataset.job, { headers: { Accept: "application/json" }, credentials: "same-origin" })
          .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
          .then((state) => {
            paint(state);
            if (badge) badge.textContent = state.status.charAt(0).toUpperCase() + state.status.slice(1);
            if (state.status === "completed" || state.status === "failed") {
              window.location.reload();
              return;
            }
            delay = Math.min(delay + 250, 3000);
            setTimeout(poll, delay);
          })
          .catch(() => setTimeout(poll, 4000));
      };
      setTimeout(poll, 600);
    }
  }

  /* ---------------------------------------------------------- conditional fields */
  function bindToggle(inputs, targets, isOn) {
    const update = () => targets.forEach((t) => { t.hidden = !isOn(t); });
    inputs.forEach((i) => i.addEventListener("change", update));
    update();
  }

  // Combined workflow: show the mode only for rewrite, the template only for format.
  $$("form[data-pipeline]").forEach((form) => {
    const boxes = $$("input[name=steps]", form);
    bindToggle(boxes, $$("[data-show-when]", form), (t) =>
      boxes.some((b) => b.checked && b.value === t.dataset.showWhen));
  });

  // Rewrite: custom instructions only for the custom mode.
  const modeRadios = $$("input[name=mode][type=radio]");
  const customBox = $("[data-show-when-mode]");
  if (modeRadios.length && customBox) {
    bindToggle(modeRadios, [customBox], () => modeRadios.some((r) => r.checked && r.value === "custom")
      || !!customBox.querySelector(".errors"));
  }

  // Apply template: section list only for "selected sections".
  const scopeRadios = $$("input[name=scope]");
  const scopeBox = $("[data-show-when-scope]");
  if (scopeRadios.length && scopeBox) {
    bindToggle(scopeRadios, [scopeBox], () => scopeRadios.some((r) => r.checked && r.value === "selected"));
  }

  // Split: offer only the methods that fit the chosen document.
  const splitForm = $("form[data-split]");
  if (splitForm && $("#doc-types")) {
    const types = JSON.parse($("#doc-types").textContent);
    const methods = JSON.parse($("#split-methods").textContent);
    const docSel = $("select[name=document]", splitForm);
    const methodSel = $("select[name=method]", splitForm);
    const all = Array.from(methodSel.options).map((o) => ({ value: o.value, text: o.textContent }));
    const sections = $$("[data-for-method]", splitForm);

    const showSections = () => {
      sections.forEach((s) => { s.hidden = !s.dataset.forMethod.split(" ").includes(methodSel.value); });
    };
    const refill = () => {
      const kind = types[docSel.value];
      const allowed = kind ? methods[kind] : all.map((o) => o.value);
      const keep = methodSel.value;
      methodSel.innerHTML = "";
      all.filter((o) => o.value && allowed.includes(o.value)).forEach((o) => {
        methodSel.add(new Option(o.text, o.value, false, o.value === keep));
      });
      showSections();
    };
    docSel.addEventListener("change", refill);
    methodSel.addEventListener("change", showSections);
    refill();
  }

  // Review: select all / none.
  $$("[data-check-all]").forEach((b) => b.addEventListener("click", () =>
    $$(`input[name=${b.dataset.checkAll}]`).forEach((c) => { c.checked = true; })));
  $$("[data-check-none]").forEach((b) => b.addEventListener("click", () =>
    $$(`input[name=${b.dataset.checkNone}]`).forEach((c) => { c.checked = false; })));

  /* ---------------------------------------------------------- image editor */
  const editor = $("form[data-image-editor]");
  if (editor) {
    const img = $("[data-preview]", editor);
    const canvas = $("[data-canvas]", editor);
    const resultEl = $("[data-result]", editor);
    const warnEl = $("[data-warnings]", editor);
    const opsField = $("input[name=ops]", editor);
    const replacement = $("[data-replacement]", editor);
    const originalSrc = img.src;
    let rotate = 0;
    let timer = null;
    let inflight = null;

    function collect() {
      const ops = {};
      const crop = { x: 0, y: 0, r: 0, b: 0 };
      $$("[data-op]", editor).forEach((el) => {
        const key = el.dataset.op;
        if (key.startsWith("crop.")) { crop[key.slice(5)] = parseFloat(el.value) || 0; return; }
        if (el.type === "checkbox") { if (el.checked) ops[key] = true; return; }
        if (el.value === "" || el.value === undefined) return;
        if (el.type === "range") {
          const v = parseFloat(el.value);
          const neutral = key === "denoise" ? 0 : 1;
          if (Math.abs(v - neutral) > 0.001) ops[key] = v;
          return;
        }
        ops[key] = el.type === "number" ? parseInt(el.value, 10) : el.value;
      });
      if (crop.x || crop.y || crop.r || crop.b) {
        ops.crop = { x: crop.x, y: crop.y, w: Math.max(5, 100 - crop.x - crop.r), h: Math.max(5, 100 - crop.y - crop.b) };
      }
      if (rotate) ops.rotate = rotate;
      return ops;
    }

    function hasReplacement() { return replacement && replacement.files && replacement.files.length > 0; }

    function refresh() {
      const ops = collect();
      opsField.value = JSON.stringify(ops);
      if (!Object.keys(ops).length && !hasReplacement()) {
        img.src = originalSrc;
        resultEl.textContent = "Edited: no changes yet";
        warnEl.hidden = true;
        return;
      }
      const data = new FormData();
      data.append("csrfmiddlewaretoken", csrf(editor));
      data.append("ops", JSON.stringify(ops));
      if (hasReplacement()) data.append("replacement", replacement.files[0]);
      if (inflight) inflight.abort();
      inflight = new AbortController();
      canvas.classList.add("is-loading");
      fetch(editor.dataset.previewUrl, { method: "POST", body: data, credentials: "same-origin", signal: inflight.signal })
        .then((r) => r.json())
        .then((res) => {
          canvas.classList.remove("is-loading");
          if (!res.ok) { showWarnings([res.error]); return; }
          img.src = res.src;
          resultEl.textContent = `Edited: ${res.format}, ${res.width} × ${res.height} px, ${formatBytes(res.bytes)}`;
          showWarnings(res.warnings);
        })
        .catch((err) => { if (err.name !== "AbortError") { canvas.classList.remove("is-loading"); showWarnings(["The preview could not be updated."]); } });
    }

    function showWarnings(list) {
      if (list && list.length) { warnEl.textContent = list.join(" "); warnEl.hidden = false; }
      else { warnEl.hidden = true; }
    }

    function formatBytes(n) {
      if (n < 1024) return n + " B";
      if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
      return (n / 1048576).toFixed(2) + " MB";
    }

    const schedule = () => { clearTimeout(timer); timer = setTimeout(refresh, 350); };

    $$("[data-op]", editor).forEach((el) => {
      const out = el.parentElement.querySelector("output");
      const label = () => {
        if (!out) return;
        out.textContent = el.dataset.op.startsWith("crop.") ? el.value + "%" :
          el.dataset.op === "denoise" ? el.value : parseFloat(el.value).toFixed(el.step === "0.1" ? 1 : 2);
      };
      el.addEventListener("input", () => { label(); schedule(); });
      el.addEventListener("change", schedule);
    });
    if (replacement) replacement.addEventListener("change", schedule);

    $("[data-rotate]", editor).addEventListener("click", () => { rotate = (rotate + 90) % 360; schedule(); });

    $("[data-reset]", editor).addEventListener("click", () => {
      $$("[data-op]", editor).forEach((el) => {
        if (el.type === "checkbox") el.checked = false;
        else if (el.type === "range") { el.value = el.dataset.op === "denoise" || el.dataset.op.startsWith("crop.") ? 0 : 1; el.dispatchEvent(new Event("input")); }
        else el.value = "";
      });
      rotate = 0;
      if (replacement) replacement.value = "";
      refresh();
    });

    editor.addEventListener("submit", () => { opsField.value = JSON.stringify(collect()); });

    const aiRun = $("[data-ai-run]", editor);
    if (aiRun) {
      aiRun.addEventListener("click", () => {
        const data = new FormData();
        data.append("csrfmiddlewaretoken", csrf(editor));
        data.append("instruction", $("[data-ai-instruction]", editor).value);
        data.append("approve", $("[data-ai-approve]", editor).checked ? "1" : "0");
        aiRun.disabled = true;
        canvas.classList.add("is-loading");
        fetch(editor.dataset.aiUrl, { method: "POST", body: data, credentials: "same-origin" })
          .then((r) => r.json())
          .then((res) => {
            if (!res.ok) { showWarnings([res.error]); return; }
            img.src = res.src;
            // Offer the suggestion as the replacement so "Save" uses it after confirmation.
            return fetch(res.src).then((r) => r.blob()).then((blob) => {
              const dt = new DataTransfer();
              dt.items.add(new File([blob], "ai-suggestion.png", { type: "image/png" }));
              replacement.files = dt.files;
              showWarnings(["AI suggestion loaded as the replacement image. Tick “Replace the original image” to save it."]);
            });
          })
          .finally(() => { aiRun.disabled = false; canvas.classList.remove("is-loading"); });
      });
    }
  }
})();
