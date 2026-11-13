"use strict";

const $ = (selector) => document.querySelector(selector);

const state = {
  status: null,
  llm: null,
  file: null,
  sample: null,
  jobId: null,
  job: null,
  rendered: 0,
  timer: null,
  busy: false,
};

const els = {
  devicePill: $("#device-pill"),
  llmPill: $("#llm-pill"),
  maxSize: $("#max-size"),
  dropzone: $("#dropzone"),
  fileInput: $("#file-input"),
  fileChip: $("#file-chip"),
  fileName: $("#file-chip .file-name"),
  samples: $("#samples"),
  sampleList: $("#sample-list"),
  model: $("#model"),
  modelHint: $("#model-hint"),
  language: $("#language"),
  task: $("#task"),
  vad: $("#vad"),
  words: $("#words"),
  start: $("#start"),
  error: $("#error"),
  progressWrap: $("#progress-wrap"),
  phase: $("#phase"),
  percent: $("#progress-percent"),
  bar: $("#progress-bar"),
  track: $(".progress-track"),
  empty: $("#empty"),
  meta: $("#job-meta"),
  segments: $("#segments"),
  panelTranscript: $("#panel-transcript"),
  panelSummary: $("#panel-summary"),
  tabTranscript: $("#tab-transcript"),
  tabSummary: $("#tab-summary"),
  summaryOutput: $("#summary-output"),
  summaryHint: $("#summary-hint"),
  summarize: $("#summarize"),
  focus: $("#focus"),
};

// ---------------------------------------------------------------- init ----

async function init() {
  bindEvents();
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error(await errorDetail(response));
    state.status = await response.json();
    applyStatus(state.status);
    fetchLlmStatus();
  } catch (error) {
    showError(`Cannot reach the Whisper Lab server: ${error.message}`);
  }
}

async function fetchLlmStatus() {
  try {
    const response = await fetch("/api/llm");
    if (!response.ok) throw new Error(await errorDetail(response));
    state.llm = await response.json();
  } catch {
    state.llm = { available: false, message: "Cannot check the local LLM server." };
  }
  updateLlmPill();
  if (state.job?.status === "done") {
    els.summarize.disabled = !state.llm.available;
  }
}

function updateLlmPill() {
  const available = Boolean(state.llm?.available);
  els.llmPill.textContent = available ? "Ollama ready" : "Ollama offline";
  els.llmPill.className = `pill ${available ? "ok" : "warn"}`;
  els.llmPill.title = state.llm?.message || "";
}

function applyStatus(status) {
  const gpu = status.device === "cuda";
  els.devicePill.textContent = gpu
    ? `GPU · CUDA (${status.compute_type})`
    : `CPU · ${status.compute_type}`;
  els.devicePill.className = `pill ${gpu ? "ok" : ""}`.trim();

  els.maxSize.textContent = status.max_upload_mb;

  els.model.innerHTML = "";
  for (const model of status.models) {
    const option = document.createElement("option");
    option.value = model.name;
    option.textContent = `${model.name} — ${model.size}`;
    option.selected = model.name === status.default_model;
    els.model.append(option);
  }
  updateModelHint();

  els.language.innerHTML = "";
  for (const [code, label] of status.languages) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = label;
    els.language.append(option);
  }

  if (status.samples.length) {
    els.samples.hidden = false;
    els.sampleList.innerHTML = "";
    for (const sample of status.samples) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sample";
      button.dataset.name = sample.name;
      button.textContent = sample.name;
      button.title = `${sample.size_mb} MB`;
      els.sampleList.append(button);
    }
  }
}

function updateModelHint() {
  const model = state.status?.models.find((item) => item.name === els.model.value);
  els.modelHint.textContent = model ? `${model.note} · ${model.speed} realtime` : "";
}

// -------------------------------------------------------------- events ----

function bindEvents() {
  els.fileInput.addEventListener("change", () => {
    const file = els.fileInput.files[0];
    if (file) selectFile(file);
  });

  els.dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    els.dropzone.classList.add("dragging");
  });
  els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("dragging"));
  els.dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    els.dropzone.classList.remove("dragging");
    const file = event.dataTransfer?.files?.[0];
    if (file) selectFile(file);
  });

  els.fileChip.addEventListener("click", (event) => {
    if (event.target.closest("[data-action='clear-file']")) clearSelection();
  });

  els.sampleList.addEventListener("click", (event) => {
    const button = event.target.closest(".sample");
    if (button) selectSample(button.dataset.name);
  });

  els.model.addEventListener("change", updateModelHint);
  els.start.addEventListener("click", startTranscription);
  els.tabTranscript.addEventListener("click", () => switchTab("transcript"));
  els.tabSummary.addEventListener("click", () => switchTab("summary"));
  els.summarize.addEventListener("click", summarizeJob);

  document.querySelector("[data-action='copy']").addEventListener("click", copyTranscript);
}

function selectFile(file) {
  clearError();
  if (state.status && file.size > state.status.max_upload_mb * 1024 * 1024) {
    showError(`That file is larger than ${state.status.max_upload_mb} MB.`);
    return;
  }
  state.file = file;
  state.sample = null;
  els.fileName.textContent = `${file.name} · ${formatBytes(file.size)}`;
  els.fileChip.hidden = false;
  for (const button of els.sampleList.querySelectorAll(".sample")) {
    button.classList.remove("selected");
  }
  updateStartState();
}

function selectSample(name) {
  clearError();
  state.file = null;
  state.sample = name;
  els.fileInput.value = "";
  els.fileChip.hidden = true;
  for (const button of els.sampleList.querySelectorAll(".sample")) {
    button.classList.toggle("selected", button.dataset.name === name);
  }
  updateStartState();
}

function clearSelection() {
  state.file = null;
  state.sample = null;
  els.fileInput.value = "";
  els.fileChip.hidden = true;
  for (const button of els.sampleList.querySelectorAll(".sample")) {
    button.classList.remove("selected");
  }
  updateStartState();
}

function updateStartState() {
  els.start.disabled = state.busy || !(state.file || state.sample);
}

// --------------------------------------------------------- transcription ----

async function startTranscription() {
  if (state.busy || !(state.file || state.sample)) return;
  clearError();
  resetResults();
  setBusy(true);

  const settings = {
    model: els.model.value,
    language: els.language.value,
    task: els.task.value,
    vad: els.vad.checked,
    words: els.words.checked,
  };

  try {
    let response;
    if (state.file) {
      const form = new FormData();
      form.append("file", state.file);
      for (const [key, value] of Object.entries(settings)) form.append(key, String(value));
      response = await fetch("/api/jobs", { method: "POST", body: form });
    } else {
      response = await fetch("/api/jobs/sample", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: state.sample, ...settings }),
      });
    }
    if (!response.ok) throw new Error(await errorDetail(response));
    const job = await response.json();
    state.jobId = job.id;
    els.empty.hidden = true;
    showProgress(job);
    poll();
  } catch (error) {
    showError(error.message);
    setBusy(false);
  }
}

function poll() {
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    try {
      const response = await fetch(`/api/jobs/${state.jobId}`);
      if (!response.ok) throw new Error(await errorDetail(response));
      const job = await response.json();
      renderJob(job);
      if (job.status !== "done" && job.status !== "error") poll();
    } catch (error) {
      showError(error.message);
      setBusy(false);
    }
  }, 700);
}

function renderJob(job) {
  state.job = job;

  if (job.status === "error") {
    showError(job.error || "Transcription failed.");
    els.phase.textContent = "Failed";
    els.track.classList.remove("indeterminate");
    els.empty.hidden = false;
    els.panelTranscript.hidden = true;
    els.panelSummary.hidden = true;
    setBusy(false);
    return;
  }

  showProgress(job);
  appendSegments(job.segments);

  if (job.status === "done") {
    els.percent.textContent = "100%";
    els.bar.style.width = "100%";
    els.meta.textContent = describeJob(job);
    setDownloads(job.id);
    setBusy(false);
    els.summarize.disabled = !state.llm?.available;
    els.summaryHint.textContent = state.llm?.available
      ? "Runs entirely on your machine through Ollama."
      : "Start Ollama with a model installed to enable this step.";
    if (job.summary) renderSummary(job.summary);
    els.empty.hidden = true;
  } else {
    els.empty.hidden = true;
  }

  const transcript = state.tab === "transcript";
  els.panelTranscript.hidden = !transcript;
  els.panelSummary.hidden = transcript;
}

function showProgress(job) {
  els.progressWrap.hidden = false;
  const percent = Math.round((job.progress || 0) * 100);

  if (job.status === "queued") {
    els.phase.textContent = "Queued behind another job…";
    els.percent.textContent = "";
    els.track.classList.add("indeterminate");
    return;
  }
  if (job.status === "loading") {
    els.phase.textContent = "Loading model (first run downloads the weights)…";
    els.percent.textContent = "";
    els.track.classList.add("indeterminate");
    return;
  }

  els.track.classList.remove("indeterminate");
  els.phase.textContent = job.status === "done" ? "Finished" : "Transcribing…";
  els.percent.textContent = `${percent}%`;
  els.bar.style.width = `${percent}%`;
}

function appendSegments(segments) {
  if (!segments || segments.length === state.rendered) return;
  const stick = els.segments.scrollHeight - els.segments.scrollTop - els.segments.clientHeight < 60;
  const fragment = document.createDocumentFragment();
  for (let index = state.rendered; index < segments.length; index += 1) {
    const segment = segments[index];
    const row = document.createElement("div");
    row.className = "segment" + (segment.translated ? " translate" : "");

    const time = document.createElement("span");
    time.className = "time";
    time.textContent = `${formatTime(segment.start)}`;

    const text = document.createElement("p");
    text.textContent = segment.text;

    row.append(time, text);
    fragment.append(row);
  }
  state.rendered = segments.length;
  els.segments.append(fragment);
  if (stick) els.segments.scrollTop = els.segments.scrollHeight;
}

function describeJob(job) {
  const parts = [];
  if (job.language) parts.push(`${job.language.toUpperCase()} (${Math.round(job.language_probability * 100)}%)`);
  if (job.duration) parts.push(formatDuration(job.duration));
  if (job.elapsed) parts.push(`${(job.duration / job.elapsed).toFixed(1)}× realtime`);
  if (job.device) parts.push(`${job.device}/${job.compute_type}`);
  parts.push(job.model);
  return parts.join(" · ");
}

function setDownloads(jobId) {
  for (const link of document.querySelectorAll("[data-download]")) {
    link.href = `/api/jobs/${jobId}/download/${link.dataset.download}`;
    link.setAttribute("download", "");
  }
}

// ------------------------------------------------------------- summary ----

async function summarizeJob() {
  if (!state.job || state.job.status !== "done") return;
  clearError();
  els.summarize.disabled = true;
  const original = els.summarize.textContent;
  els.summarize.textContent = "Summarizing…";

  try {
    const response = await fetch(`/api/jobs/${state.jobId}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ focus: els.focus.value }),
    });
    if (!response.ok) throw new Error(await errorDetail(response));
    const data = await response.json();
    renderSummary(data.summary);
    switchTab("summary");
  } catch (error) {
    showError(error.message);
  } finally {
    els.summarize.textContent = original;
    els.summarize.disabled = !state.llm?.available;
  }
}

function renderSummary(markdown) {
  els.summaryOutput.innerHTML = renderMarkdown(markdown);
  els.summaryOutput.hidden = false;
}

// --------------------------------------------------------------- tabs -----

function switchTab(tab) {
  state.tab = tab;
  const transcript = tab === "transcript";
  els.tabTranscript.classList.toggle("active", transcript);
  els.tabSummary.classList.toggle("active", !transcript);
  els.tabTranscript.setAttribute("aria-selected", String(transcript));
  els.tabSummary.setAttribute("aria-selected", String(!transcript));

  const hasJob = Boolean(state.job) && state.job.status !== "error";
  els.panelTranscript.hidden = !transcript || !hasJob;
  els.panelSummary.hidden = transcript || !hasJob;
  els.empty.hidden = hasJob;

  if (!transcript && hasJob && state.job.status !== "done") {
    els.summaryHint.textContent = "Wait until the transcription finishes, then summarize.";
  }
}

async function copyTranscript() {
  if (!state.job?.text) return;
  try {
    await navigator.clipboard.writeText(state.job.text);
  } catch {
    const area = document.createElement("textarea");
    area.value = state.job.text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const button = document.querySelector("[data-action='copy']");
  const original = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => (button.textContent = original), 1200);
}

// -------------------------------------------------------------- helpers ----

function resetResults() {
  state.job = null;
  state.jobId = null;
  state.rendered = 0;
  els.segments.innerHTML = "";
  els.meta.textContent = "";
  els.summaryOutput.hidden = true;
  els.summaryOutput.innerHTML = "";
  els.summaryHint.textContent = "";
  els.empty.hidden = false;
  els.panelTranscript.hidden = true;
  els.panelSummary.hidden = true;
  switchTab("transcript");
  els.progressWrap.hidden = true;
  els.bar.style.width = "0";
  els.percent.textContent = "";
  els.phase.textContent = "Queued…";
  els.track.classList.remove("indeterminate");
}

function setBusy(busy) {
  state.busy = busy;
  els.start.textContent = busy ? "Transcribing…" : "Transcribe";
  updateStartState();
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

function clearError() {
  els.error.hidden = true;
  els.error.textContent = "";
}

async function errorDetail(response) {
  try {
    const data = await response.json();
    if (data && data.detail) return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  } catch {
    /* not JSON */
  }
  return `${response.status} ${response.statusText}`;
}

function formatTime(seconds) {
  const total = Math.floor(seconds || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatDuration(seconds) {
  const total = Math.round(seconds || 0);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours} h ${minutes % 60} min`;
  }
  return `${minutes} min ${secs} s`;
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// --------------------------------------------------- tiny Markdown renderer

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function renderMarkdown(markdown) {
  const lines = escapeHtml(markdown).split(/\r?\n/);
  const output = [];
  let index = 0;

  const isBlockStart = (line) => /^(#{1,4}\s|[-*]\s|\d+\.\s|>|\|)/.test(line.trim());

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 4);
      output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (line.trim().startsWith("|")) {
      const rows = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        rows.push(lines[index].trim());
        index += 1;
      }
      output.push(renderTable(rows));
      continue;
    }

    if (/^[-*]\s+/.test(line.trim())) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(inline(lines[index].replace(/^\s*[-*]\s+/, "")));
        index += 1;
      }
      output.push(`<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(line.trim())) {
      const items = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(inline(lines[index].replace(/^\s*\d+\.\s+/, "")));
        index += 1;
      }
      output.push(`<ol>${items.map((item) => `<li>${item}</li>`).join("")}</ol>`);
      continue;
    }

    if (line.trim().startsWith(">")) {
      const quoted = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoted.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      output.push(`<blockquote>${inline(quoted.join(" "))}</blockquote>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(inline(lines[index].trim()));
      index += 1;
    }
    output.push(`<p>${paragraph.join(" ")}</p>`);
  }

  return output.join("\n");
}

function renderTable(rows) {
  const cells = (row) =>
    row
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());

  const header = cells(rows[0]);
  const isSeparator = (row) => cells(row).every((cell) => /^:?-{2,}:?$/.test(cell));
  const body = rows.slice(1).filter((row) => !isSeparator(row)).map(cells);

  const head = `<thead><tr>${header.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead>`;
  const rowsHtml = body
    .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${head}<tbody>${rowsHtml}</tbody></table>`;
}

init();
