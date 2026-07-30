const filePathInput = document.querySelector("#filePath");
const startBtn = document.querySelector("#startBtn");
const clearLogsBtn = document.querySelector("#clearLogsBtn");
const message = document.querySelector("#message");
const statusBadge = document.querySelector("#statusBadge");
const logsEl = document.querySelector("#logs");
const filesEl = document.querySelector("#files");
const totalCount = document.querySelector("#totalCount");
const savedCount = document.querySelector("#savedCount");
const skippedCount = document.querySelector("#skippedCount");
const jobIdEl = document.querySelector("#jobId");

let pollTimer = null;

function setStatus(status) {
  statusBadge.className = `status ${status}`;
  statusBadge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

function setMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

function renderLogs(logs) {
  logsEl.textContent = logs.length ? logs.join("\n") : "Waiting for scan...";
  logsEl.scrollTop = logsEl.scrollHeight;
}

function renderFiles(files) {
  if (!files || files.length === 0) {
    filesEl.className = "files empty";
    filesEl.textContent = "No output yet.";
    return;
  }

  filesEl.className = "files";
  filesEl.innerHTML = files
    .map(
      (file) => `
        <div class="file-row">
          <div class="file-name" title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</div>
          <a class="download" href="${file.download_url}">Download</a>
        </div>
      `,
    )
    .join("");
}

function renderStats(stats = {}) {
  totalCount.textContent = stats.total ?? 0;
  savedCount.textContent = stats.saved ?? 0;
  skippedCount.textContent = stats.skipped ?? 0;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function startScan() {
  const filePath = filePathInput.value.trim();
  if (!filePath) {
    setMessage("Enter a folder path first.", true);
    return;
  }

  clearInterval(pollTimer);
  startBtn.disabled = true;
  setStatus("running");
  setMessage("Starting scan...");
  renderLogs(["Starting scan..."]);
  renderFiles([]);
  renderStats();
  jobIdEl.textContent = "-";

  try {
    const response = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: filePath }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Scan request failed.");
    }

    jobIdEl.textContent = data.job_id;
    setMessage("Scan is running.");
    pollTimer = setInterval(() => pollJob(data.job_id), 800);
    await pollJob(data.job_id);
  } catch (error) {
    startBtn.disabled = false;
    setStatus("error");
    setMessage(error.message, true);
    renderLogs([`[ERROR] ${error.message}`]);
  }
}

async function pollJob(jobId) {
  try {
    const response = await fetch(`/api/job/${jobId}`);
    const job = await response.json();

    if (!response.ok) {
      throw new Error(job.error || "Could not load job status.");
    }

    setStatus(job.status);
    renderLogs(job.logs || []);
    renderFiles(job.files || []);
    renderStats(job.stats || {});

    if (job.status === "done") {
      clearInterval(pollTimer);
      startBtn.disabled = false;
      setMessage("Completed successfully.");
    }

    if (job.status === "error") {
      clearInterval(pollTimer);
      startBtn.disabled = false;
      setMessage(job.error || "Scan failed.", true);
    }
  } catch (error) {
    clearInterval(pollTimer);
    startBtn.disabled = false;
    setStatus("error");
    setMessage(error.message, true);
  }
}

startBtn.addEventListener("click", startScan);
clearLogsBtn.addEventListener("click", () => renderLogs([]));
filePathInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    startScan();
  }
});
