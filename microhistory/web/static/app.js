/* MicroHistory Web UI */

// ---- Generate page ----

const modeSelect = document.getElementById("mode-select");
if (modeSelect) {
  modeSelect.addEventListener("change", () => {
    const isShorts = modeSelect.value === "shorts";
    document.getElementById("shorts-options").hidden = !isShorts;
    document.getElementById("longform-options").hidden = isShorts;
  });
}

const genForm = document.getElementById("generate-form");
if (genForm) {
  genForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(genForm);
    const body = {
      topic: fd.get("topic") || "auto",
      mode: fd.get("mode"),
      video_backend: fd.get("video_backend"),
      daily_count: parseInt(fd.get("daily_count")) || 1,
      target_length: fd.get("target_length") || "9min",
    };

    document.getElementById("submit-btn").disabled = true;
    document.getElementById("submit-btn").textContent = "Starting...";

    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.job_id) {
        startProgressStream(data.job_id);
      }
    } catch (err) {
      alert("Error: " + err.message);
      document.getElementById("submit-btn").disabled = false;
      document.getElementById("submit-btn").textContent = "Generate";
    }
  });
}

function startProgressStream(jobId) {
  const panel = document.getElementById("progress-panel");
  const list = document.getElementById("progress-list");
  const status = document.getElementById("progress-status");
  panel.hidden = false;
  list.innerHTML = "";
  status.textContent = "Connecting...";

  const source = new EventSource("/api/jobs/" + jobId + "/events");

  source.onmessage = (e) => {
    const event = JSON.parse(e.data);

    if (event.type === "step") {
      // Mark previous running step as completed
      const prev = list.querySelector("li.running");
      if (prev) {
        prev.className = "completed";
      }
      const li = document.createElement("li");
      li.className = "running";
      li.textContent = event.name;
      list.appendChild(li);
      status.textContent = event.name + "...";
    } else if (event.type === "log") {
      status.textContent = event.message;
    } else if (event.type === "done") {
      source.close();
      // Mark last running step as completed
      const prev = list.querySelector("li.running");
      if (prev) {
        prev.className = event.status === "completed" ? "completed" : "failed";
      }

      if (event.status === "completed") {
        status.textContent = "Done!";
        const donePanel = document.getElementById("progress-done");
        donePanel.hidden = false;
        document.getElementById("download-zip").href = "/api/jobs/" + jobId + "/zip";
        document.getElementById("view-files").href = "/jobs#" + jobId;
      } else {
        status.textContent = "Failed: " + (event.error || "unknown error");
      }

      document.getElementById("submit-btn").disabled = false;
      document.getElementById("submit-btn").textContent = "Generate";
    }
  };

  source.onerror = () => {
    status.textContent = "Connection lost. Check the Jobs page for results.";
    source.close();
    document.getElementById("submit-btn").disabled = false;
    document.getElementById("submit-btn").textContent = "Generate";
  };
}

// ---- Jobs page ----

const jobsBody = document.getElementById("jobs-body");
if (jobsBody) {
  loadJobs();
}

async function loadJobs() {
  try {
    const res = await fetch("/api/jobs");
    const jobs = await res.json();
    if (jobs.length === 0) {
      jobsBody.innerHTML = '<tr><td colspan="5">No jobs yet. Go to <a href="/">Generate</a> to create one.</td></tr>';
      return;
    }
    jobsBody.innerHTML = jobs.map((j) => `
      <tr>
        <td>${esc(j.topic)}</td>
        <td>${esc(j.mode)}</td>
        <td><span class="status-badge ${j.status}">${j.status}</span></td>
        <td>${j.created ? new Date(j.created).toLocaleString() : ""}</td>
        <td>
          ${j.status === "completed" ? `
            <a href="/api/jobs/${j.job_id}/zip">Download ZIP</a> |
            <a href="#" onclick="showFiles('${j.job_id}', '${esc(j.topic)}'); return false;">Browse Files</a>
          ` : ""}
        </td>
      </tr>
    `).join("");

    // Auto-open if hash matches a job ID
    const hash = window.location.hash.slice(1);
    if (hash) {
      const match = jobs.find((j) => j.job_id === hash);
      if (match && match.status === "completed") {
        showFiles(hash, match.topic);
      }
    }
  } catch (err) {
    jobsBody.innerHTML = '<tr><td colspan="5">Error loading jobs</td></tr>';
  }
}

async function showFiles(jobId, topic) {
  const dialog = document.getElementById("files-dialog");
  const title = document.getElementById("files-title");
  const body = document.getElementById("files-body");

  title.textContent = "Files — " + topic;
  body.innerHTML = "<tr><td colspan='3'>Loading...</td></tr>";
  dialog.showModal();

  try {
    const res = await fetch("/api/jobs/" + jobId + "/files");
    const files = await res.json();
    body.innerHTML = files.map((f) => `
      <tr>
        <td>${esc(f.path)}</td>
        <td>${f.size_display}</td>
        <td><a href="/api/jobs/${jobId}/files/${encodeURIComponent(f.path)}" download>Download</a></td>
      </tr>
    `).join("");
  } catch {
    body.innerHTML = "<tr><td colspan='3'>Error loading files</td></tr>";
  }
}

// ---- Settings page ----

const settingsForm = document.getElementById("settings-form");
if (settingsForm) {
  loadSettings();

  settingsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(settingsForm);
    const body = {};
    for (const [key, val] of fd.entries()) {
      if (val) body[key] = val;
    }

    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const saved = document.getElementById("settings-saved");
      saved.hidden = false;
      setTimeout(() => { saved.hidden = true; }, 3000);
      loadSettings();
    } catch (err) {
      alert("Error saving: " + err.message);
    }
  });
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    for (const key of ["GOOGLE_API_KEY", "ELEVENLABS_API_KEY", "RUNWAY_API_KEY", "ELEVENLABS_VOICE_ID"]) {
      const el = document.getElementById("status-" + key);
      if (el) {
        const val = data[key] || "not set";
        el.textContent = "Current: " + val;
        el.style.color = val === "not set" ? "var(--pico-del-color)" : "var(--pico-ins-color)";
      }
    }
  } catch { /* ignore */ }
}

// ---- Helpers ----

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str || "";
  return d.innerHTML;
}
