const logBox = document.getElementById("log-box");

function log(msg) {
  const line = document.createElement("div");
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logBox.prepend(line);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------- Sidebar navigation ----------
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => (v.hidden = true));
    btn.classList.add("active");
    document.getElementById(`view-${btn.dataset.view}`).hidden = false;
  });
});

// ---------- Proxies ----------
async function refreshProxies() {
  const proxies = await api("/api/proxies");
  const tbody = document.querySelector("#proxy-table tbody");
  const empty = document.getElementById("proxy-empty");
  tbody.innerHTML = "";
  empty.hidden = proxies.length > 0;

  for (const p of proxies) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.id}</td>
      <td>${p.scheme}://${p.host}:${p.port}</td>
      <td><span class="status status-${p.status}">${p.status}</span></td>
      <td>${p.latency_ms ?? "-"}</td>
      <td>${p.observed_ip ?? "-"}</td>
      <td class="col-actions"><button data-id="${p.id}" class="btn-icon danger del-proxy">Xoá</button></td>`;
    tbody.appendChild(tr);
  }
  document.querySelectorAll(".del-proxy").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await api(`/api/proxies/${btn.dataset.id}`, { method: "DELETE" });
      refreshProxies();
    })
  );
}

document.getElementById("proxy-file").addEventListener("change", async (e) => {
  if (!e.target.files.length) return;
  const formData = new FormData();
  formData.append("file", e.target.files[0]);
  const res = await api("/api/proxies/import", { method: "POST", body: formData });
  log(`Đã import ${res.imported} proxy`);
  e.target.value = "";
  refreshProxies();
});

document.getElementById("health-check-btn").addEventListener("click", async () => {
  log("Đang health check toàn bộ proxy...");
  await api("/api/proxies/health-check", { method: "POST" });
  log("Health check xong");
  refreshProxies();
});

// ---------- Profiles ----------
const createForm = document.getElementById("profile-form");
document.getElementById("open-create-profile").addEventListener("click", () => {
  createForm.hidden = !createForm.hidden;
});
document.getElementById("cancel-create-profile").addEventListener("click", () => {
  createForm.hidden = true;
});

async function refreshProfiles() {
  const q = document.getElementById("profile-search").value.trim().toLowerCase();
  const profiles = await api("/api/profiles");
  const filtered = q ? profiles.filter((p) => p.name.toLowerCase().includes(q)) : profiles;

  const tbody = document.querySelector("#profile-table tbody");
  const empty = document.getElementById("profile-empty");
  tbody.innerHTML = "";
  empty.hidden = filtered.length > 0;

  for (const p of filtered) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="status status-${p.status}"></span></td>
      <td>${p.name}</td>
      <td>127.0.0.1:${p.local_port}</td>
      <td><span class="status status-${p.status}">${p.status}</span></td>
      <td>${p.active_connections} kết nối${p.launched_apps ? ` · ${p.launched_apps} app` : ""}</td>
      <td><span class="toggle-badge ${p.auto_rotate_enabled ? "on" : ""}">${p.auto_rotate_enabled ? "Bật" : "Tắt"}</span></td>
      <td class="col-actions">
        <button data-id="${p.id}" class="btn-icon start-profile">Start</button>
        <button data-id="${p.id}" class="btn-icon stop-profile">Stop</button>
        <button data-id="${p.id}" class="btn-icon launch-profile">Mở app</button>
        <button data-id="${p.id}" class="btn-icon rotate-profile">Đổi IP</button>
        <button data-id="${p.id}" class="btn-icon edit-profile">Sửa</button>
        <button data-id="${p.id}" class="btn-icon leak-test-profile">Leak Test</button>
        <button data-id="${p.id}" class="btn-icon danger del-profile">Xoá</button>
      </td>`;
    tbody.appendChild(tr);
  }

  const bind = (cls, handler) =>
    document.querySelectorAll(cls).forEach((btn) => btn.addEventListener("click", () => handler(btn.dataset.id)));

  bind(".start-profile", async (id) => { await api(`/api/profiles/${id}/start`, { method: "POST" }); log(`Profile ${id} started`); refreshProfiles(); });
  bind(".stop-profile", async (id) => { await api(`/api/profiles/${id}/stop`, { method: "POST" }); log(`Profile ${id} stopped`); refreshProfiles(); });
  bind(".rotate-profile", async (id) => { await api(`/api/profiles/${id}/rotate`, { method: "POST" }); log(`Profile ${id} đã đổi IP`); refreshProfiles(); });
  bind(".launch-profile", async (id) => {
    const browser = document.getElementById("browser-select").value;
    try {
      const res = await api(`/api/profiles/${id}/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ browser }),
      });
      log(`Đã mở ${browser} (PID ${res.pid}) cho profile ${id}`);
      refreshProfiles();
    } catch (err) {
      log(`Lỗi mở app profile ${id}: ${err.message}`);
    }
  });
  bind(".edit-profile", (id) => openEditForm(filtered.find((p) => String(p.id) === String(id))));
  bind(".leak-test-profile", async (id) => {
    const result = await api(`/api/profiles/${id}/leak-test`, { method: "POST" });
    log(`Leak test profile ${id}: IP ${result.ip_leak_pass ? "PASS" : "FAIL"}, kill-switch ${result.kill_switch_pass ? "PASS" : "FAIL"}`);
  });
  bind(".del-profile", async (id) => { await api(`/api/profiles/${id}`, { method: "DELETE" }); refreshProfiles(); });
}

// ---------- Edit profile ----------
const editForm = document.getElementById("profile-edit-form");
const editError = document.getElementById("profile-edit-error");

async function openEditForm(p) {
  if (!p) return;
  createForm.hidden = true;
  editError.hidden = true;
  document.getElementById("edit-profile-id").value = p.id;
  document.getElementById("edit-profile-label").textContent = `#${p.id} — ${p.name}`;
  document.getElementById("edit-profile-name").value = p.name;
  document.getElementById("edit-profile-proxy-ids").value = p.proxy_ids.join(",");
  document.getElementById("edit-auto-rotate").checked = p.auto_rotate_enabled;
  document.getElementById("edit-auto-rotate-seconds").value = p.auto_rotate_seconds;
  document.getElementById("edit-assigned-apps").value = (p.assigned_process_names || []).join(", ");
  editForm.hidden = false;
  await loadProcesses();
}

async function loadProcesses() {
  const picker = document.getElementById("process-picker");
  try {
    const { processes } = await api("/api/processes");
    picker.innerHTML = `<option value="">+ Thêm từ tiến trình đang chạy…</option>` +
      processes.map((name) => `<option value="${name}">${name}</option>`).join("");
  } catch {
    picker.innerHTML = `<option value="">(không lấy được danh sách tiến trình)</option>`;
  }
}

document.getElementById("process-picker").addEventListener("change", (e) => {
  const name = e.target.value;
  if (!name) return;
  const input = document.getElementById("edit-assigned-apps");
  const current = input.value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!current.includes(name)) current.push(name);
  input.value = current.join(", ");
  e.target.value = "";
});

document.getElementById("cancel-edit-profile").addEventListener("click", () => {
  editForm.hidden = true;
});

editForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  editError.hidden = true;
  const id = document.getElementById("edit-profile-id").value;
  const proxyIds = document.getElementById("edit-profile-proxy-ids").value
    .split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n));
  const apps = document.getElementById("edit-assigned-apps").value
    .split(",").map((s) => s.trim()).filter(Boolean);
  const payload = {
    name: document.getElementById("edit-profile-name").value.trim(),
    proxy_ids: proxyIds,
    assigned_process_names: apps,
    auto_rotate_enabled: document.getElementById("edit-auto-rotate").checked,
    auto_rotate_seconds: parseInt(document.getElementById("edit-auto-rotate-seconds").value, 10) || 600,
  };
  try {
    await api(`/api/profiles/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    let msg = err.message;
    try { msg = JSON.parse(err.message).detail || msg; } catch {}
    editError.textContent = `Không lưu được: ${msg}`;
    editError.hidden = false;
    return;
  }
  log(`Đã cập nhật profile ${id}`);
  editForm.hidden = true;
  refreshProfiles();
});

async function loadBrowsers() {
  const select = document.getElementById("browser-select");
  try {
    const { available } = await api("/api/browsers");
    const options = available.length ? available : ["chrome", "edge", "brave"];
    select.innerHTML = options.map((b) => `<option value="${b}">${b}</option>`).join("");
    if (!available.length) {
      log("Chưa phát hiện trình duyệt nào — danh sách mặc định được dùng, có thể mở lỗi.");
    }
  } catch {
    select.innerHTML = ["chrome", "edge", "brave"].map((b) => `<option value="${b}">${b}</option>`).join("");
  }
}

document.getElementById("profile-search").addEventListener("input", () => refreshProfiles());

const formError = document.getElementById("profile-form-error");

function showFormError(msg) {
  formError.textContent = msg;
  formError.hidden = false;
}

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;
  const name = document.getElementById("profile-name").value.trim();
  const proxyIds = document.getElementById("profile-proxy-ids").value
    .split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n));

  if (!proxyIds.length) {
    showFormError("Nhập ít nhất 1 Proxy ID. Chưa có proxy? Vào 'Proxy Pool' import trước đã.");
    return;
  }

  try {
    await api("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, proxy_ids: proxyIds }),
    });
  } catch (err) {
    // Backend tra JSON {detail: "..."} khi 400 -> rut message cho de doc
    let msg = err.message;
    try { msg = JSON.parse(err.message).detail || msg; } catch {}
    showFormError(`Không tạo được profile: ${msg}`);
    return;
  }

  log(`Đã tạo profile ${name}`);
  createForm.reset();
  createForm.hidden = true;
  refreshProfiles();
});

// ---------- WebSocket realtime ----------
function connectWs() {
  const ws = new WebSocket(`ws://${location.host}/ws/logs`);
  ws.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    log(`Event: ${JSON.stringify(data)}`);
    if (data.type.startsWith("profile") || data.type === "ip_rotated" || data.type === "auto_failover") refreshProfiles();
    if (data.type === "health_check_done") { refreshProxies(); refreshProfiles(); }
    if (data.type === "auto_failover") log(`⚠ Tự chuyển proxy cho profile: ${(data.profile_ids || []).join(", ")} (proxy cũ chết)`);
  };
  ws.onclose = () => setTimeout(connectWs, 2000);
}

refreshProxies();
refreshProfiles();
loadBrowsers();
connectWs();
