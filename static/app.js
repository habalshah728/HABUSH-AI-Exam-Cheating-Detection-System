// ══════════════════════════════════════════
// HABUSH CMS — Exam Monitor App
// ══════════════════════════════════════════

const state = {
  token: localStorage.getItem("bu_em_token") || "",
  user: null,
  campus: localStorage.getItem("bu_em_campus") || "",
  pendingEmail: "",
  uploadId: null,
  uploadPreview: "",
  lastVideoSessionId: null,
  liveWs: null,
  liveStream: null,
  liveTimer: null,
  camMode: "ip",         // "ip" | "browser"
  currentPage: "dashboard",
};

const $ = (id) => document.getElementById(id);
const qs = (sel) => document.querySelector(sel);

function fmtDuration(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = String(Math.floor(s / 3600)).padStart(2,"0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2,"0");
  const r = String(s % 60).padStart(2,"0");
  return `${h}:${m}:${r}`;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function riskBadge(level) {
  const cls = level==="High" ? "badge-high" : level==="Medium" ? "badge-medium" : "badge-low";
  return `<span class="badge ${cls}">${level}</span>`;
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) { logoutLocal(); throw new Error("Session expired."); }
  return res;
}

// ─── Dark / Light Theme ───
const themeBtn = $("btnTheme");
const htmlEl = document.documentElement;
const savedTheme = localStorage.getItem("bu_em_theme") || "light";
htmlEl.setAttribute("data-theme", savedTheme);
themeBtn.textContent = savedTheme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";

themeBtn.addEventListener("click", () => {
  const current = htmlEl.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  htmlEl.setAttribute("data-theme", next);
  localStorage.setItem("bu_em_theme", next);
  themeBtn.textContent = next === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";
});

// ─── Auth Banners ───
function showAuthBanner(msg, type = "info") {
  const el = $("authBanner");
  el.className = `banner banner-${type}`;
  el.innerHTML = msg;
  el.classList.remove("hidden");
}
function hideAuthBanner() { $("authBanner").classList.add("hidden"); }

// ─── Auth Tab Switching ───
document.querySelectorAll(".auth-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".auth-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    hideAuthBanner();
    const isLogin = tab.dataset.tab === "login";
    $("loginForm").classList.toggle("hidden", !isLogin);
    $("registerForm").classList.toggle("hidden", isLogin);
    $("otpForm").classList.add("hidden");
  });
});

function showOtpStep(email, demoOtp, msg) {
  state.pendingEmail = email;
  $("otpEmailLabel").textContent = email;
  $("authTabs").classList.add("hidden");
  $("loginForm").classList.add("hidden");
  $("registerForm").classList.add("hidden");
  $("otpForm").classList.remove("hidden");
  if (msg) showAuthBanner(msg, "info");
  if (demoOtp) {
    $("demoOtpBox").innerHTML = `⚠️ <strong>Demo Mode (SMTP not configured):</strong> Your verification code is <code style="font-size:1.1rem;font-weight:800;">${demoOtp}</code>`;
    $("demoOtpBox").classList.remove("hidden");
  } else {
    $("demoOtpBox").classList.add("hidden");
  }
}

// ─── Login ───
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault(); hideAuthBanner();
  const typedCampus = $("loginCampus").value.trim();
  const role = $("loginRole").value;
  if (typedCampus) {
    state.campus = typedCampus;
    localStorage.setItem("bu_em_campus", typedCampus);
  }
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: $("loginEmail").value,
      password: $("loginPassword").value,
      campus: typedCampus,
    }),
  });
  const data = await res.json();
  if (data.success && data.token) {
    state.token = data.token;
    state.campus = (data.user && data.user.campus) ? data.user.campus : typedCampus;
    if (state.campus) localStorage.setItem("bu_em_campus", state.campus);
    else localStorage.removeItem("bu_em_campus");
    localStorage.setItem("bu_em_token", data.token);
    if (data.user) data.user._role = role;
    enterPortal(data.user);
  } else if (data.requires_verification) {
    showOtpStep(data.email, data.demo_otp, data.message);
  } else {
    showAuthBanner(data.message || "Sign in failed.", "error");
  }
});

// ─── Register ───
$("registerForm").addEventListener("submit", async (e) => {
  e.preventDefault(); hideAuthBanner();
  const campus = $("regCampus").value.trim();
  const role = $("regRole").value;
  if (!campus) {
    showAuthBanner("Please enter your campus name.", "error");
    return;
  }
  const res = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      full_name: `${$("regName").value.trim()} (${role})`,
      email: $("regEmail").value,
      password: $("regPassword").value,
      campus,
    }),
  });
  const data = await res.json();
  if (data.success && data.requires_verification) {
    state.campus = campus;
    localStorage.setItem("bu_em_campus", campus);
    showOtpStep(data.email, data.demo_otp, data.message);
  } else {
    showAuthBanner(data.message || "Registration failed.", "error");
  }
});

// ─── OTP Verify ───
$("btnVerifyOtp").addEventListener("click", async () => {
  hideAuthBanner();
  const res = await fetch("/api/auth/verify-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: state.pendingEmail, code: $("otpCode").value }),
  });
  const data = await res.json();
  if (data.success && data.token) {
    state.token = data.token;
    localStorage.setItem("bu_em_token", data.token);
    $("authTabs").classList.remove("hidden");
    enterPortal(data.user);
  } else {
    showAuthBanner(data.message || "Invalid code.", "error");
  }
});

$("btnResendOtp").addEventListener("click", async () => {
  const res = await fetch("/api/auth/resend-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: state.pendingEmail }),
  });
  const data = await res.json();
  if (data.success) showOtpStep(state.pendingEmail, data.demo_otp, data.message);
  else showAuthBanner(data.message, "error");
});

$("btnBackToLogin").addEventListener("click", () => {
  $("authTabs").classList.remove("hidden");
  document.querySelectorAll(".auth-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === "login"));
  $("otpForm").classList.add("hidden");
  $("registerForm").classList.add("hidden");
  $("loginForm").classList.remove("hidden");
  hideAuthBanner();
});

// ─── Logout ───
function logoutLocal() {
  stopLiveMonitoring();
  state.token = ""; state.user = null;
  localStorage.removeItem("bu_em_token");
  $("navMgmtBtn").classList.add("hidden");
  $("portalSection").classList.add("hidden");
  $("btnLogout").classList.add("hidden");
  $("topbarUserInfo").classList.add("hidden");
  $("topbarCampus").classList.add("hidden");
  $("loginPassword").value = "";
  $("pwBanner").classList.add("hidden");
  $("changePasswordForm").reset();
  $("mgmtAccountsBody").innerHTML = "";
  $("mgmtReportsBody").innerHTML = "";
  $("authSection").classList.remove("hidden");
}

$("btnLogout").addEventListener("click", async () => {
  try { await apiFetch("/api/auth/logout", { method: "POST" }); } catch (_) {}
  logoutLocal();
});

// ─── Enter Portal ───
function enterPortal(user) {
  state.user = user;
  const activeCampus = user.campus || state.campus || "";
  state.campus = activeCampus;
  if (activeCampus) localStorage.setItem("bu_em_campus", activeCampus);

  $("topbarName").textContent = user.full_name;
  $("topbarEmail").textContent = user.email;
  if (activeCampus) {
    $("topbarCampus").textContent = activeCampus;
    $("topbarCampus").classList.remove("hidden");
  } else {
    $("topbarCampus").classList.add("hidden");
  }
  const hasMgmtAccess = Boolean(user && user.is_admin);
  $("navMgmtBtn").classList.toggle("hidden", !hasMgmtAccess);
  $("topbarUserInfo").classList.remove("hidden");
  $("btnLogout").classList.remove("hidden");
  $("authSection").classList.add("hidden");
  $("portalSection").classList.remove("hidden");
  switchPage(hasMgmtAccess ? "management" : "dashboard");
}

// ─── Navigation ───
function switchPage(page, opt = {}) {
  if (page !== "live") stopLiveMonitoring();
  if (page === "management" && !(state.user && state.user.is_admin)) {
    page = "dashboard";
  }
  state.currentPage = page;
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.page === page));
  document.querySelectorAll(".page-view").forEach(v => v.classList.add("hidden"));
  $(`page-${page}`).classList.remove("hidden");
  if (page === "dashboard") loadDashboard();
  if (page === "live") initLivePage();
  if (page === "reports") loadSessionsList(opt.sessionId ?? null);
  if (page === "management") loadManagementConsole();
}

document.querySelectorAll(".nav-btn").forEach(b => b.addEventListener("click", () => switchPage(b.dataset.page)));
document.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => switchPage(b.dataset.goto)));

// ══════════ DASHBOARD & DELETE HELPERS ══════════
async function deleteSessionRecord(sessionId, onSuccess) {
  if (!confirm(`Delete Session #${sessionId} along with all its alerts, screenshots, and PDF report?`)) return;
  try {
    const res = await apiFetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
    if (res.ok) {
      if (onSuccess) await onSuccess();
    } else {
      const data = await res.json();
      alert(data.detail || "Could not delete session.");
    }
  } catch (err) {
    alert(err.message || "Delete failed.");
  }
}

async function deleteEventRecord(eventId, onSuccess) {
  if (!confirm("Delete this alert record and its screenshot?")) return;
  try {
    const res = await apiFetch(`/api/events/${eventId}`, { method: "DELETE" });
    if (res.ok) {
      if (onSuccess) await onSuccess();
    } else {
      const data = await res.json();
      alert(data.detail || "Could not delete alert.");
    }
  } catch (err) {
    alert(err.message || "Delete failed.");
  }
}

function openSessionPdf(sessionId) {
  if (!sessionId) return;
  window.open(`/api/reports/${sessionId}/pdf?token=${encodeURIComponent(state.token)}`, "_blank");
}

async function loadDashboard() {
  try {
    const res = await apiFetch("/api/dashboard");
    const data = await res.json();
    const s = data.stats;
    $("kpiVideos").textContent = s.videos_analysed;
    $("kpiSessions").textContent = s.monitoring_sessions;
    $("kpiPeople").textContent = s.people_detected;
    $("kpiEvents").textContent = s.suspicious_activities;
    $("kpiPhones").textContent = s.phone_detections;

    const tbody = $("recentAlertsBody");
    if (!data.recent_events.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:20px;color:var(--text-muted);">No suspicious alerts recorded yet.</td></tr>`;
    } else {
      tbody.innerHTML = data.recent_events.map(e => `
        <tr>
          <td>${fmtDuration(e.timestamp_sec)}</td>
          <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(e.source_name)}</td>
          <td>${escapeHtml(e.category)}</td>
          <td>Person ${e.track_id}</td>
          <td>${riskBadge(e.risk_level)}</td>
          <td>${e.screenshot_url ? `<a class="mini-shot-link" href="${escapeHtml(e.screenshot_url)}" target="_blank">View Shot</a>` : "—"}</td>
          <td><button class="btn btn-danger btn-xs" onclick="deleteEventRecord(${e.id}, loadDashboard)">🗑 Delete</button></td>
        </tr>`).join("");
    }

    const sbody = $("recentSessionsBody");
    const sessions = data.sessions || [];
    if (!sessions.length) {
      sbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:20px;color:var(--text-muted);">No monitoring sessions recorded yet.</td></tr>`;
    } else {
      sbody.innerHTML = sessions.map(sess => `
        <tr>
          <td>#${sess.id}</td>
          <td>${escapeHtml(String(sess.mode || "").toUpperCase())}</td>
          <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(sess.source_name)}</td>
          <td>${escapeHtml(sess.campus || "—")}</td>
          <td>${sess.total_events}</td>
          <td>${riskBadge(sess.max_risk)}</td>
          <td style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-outline btn-xs" onclick="openReportSession(${sess.id})">Open</button>
            <button class="btn btn-gold btn-xs" onclick="openSessionPdf(${sess.id})">⬇ PDF</button>
            <button class="btn btn-danger btn-xs" onclick="deleteSessionRecord(${sess.id}, loadDashboard)">🗑 Delete</button>
          </td>
        </tr>`).join("");
    }
  } catch (_) {}
}

function openReportSession(sessionId) {
  switchPage("reports", { sessionId });
}

// ══════════ UPLOAD VIDEO ══════════
$("rngSkip").addEventListener("input", e => $("lblSkip").textContent = e.target.value);
$("rngConf").addEventListener("input", e => $("lblConf").textContent = Number(e.target.value).toFixed(2));
$("rngCooldown").addEventListener("input", e => $("lblCooldown").textContent = e.target.value);

$("videoDropzone").addEventListener("click", () => $("videoFileInput").click());
$("videoDropzone").addEventListener("dragover", e => { e.preventDefault(); $("videoDropzone").style.borderColor = "var(--bu-navy)"; });
$("videoDropzone").addEventListener("dragleave", () => { $("videoDropzone").style.borderColor = ""; });
$("videoDropzone").addEventListener("drop", e => {
  e.preventDefault();
  if (e.dataTransfer.files[0]) { $("videoFileInput").files = e.dataTransfer.files; $("videoFileInput").dispatchEvent(new Event("change")); }
});

$("videoFileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const form = new FormData(); form.append("file", file);
  $("videoMetaBar").textContent = `Uploading ${file.name}...`;
  $("videoMetaBar").className = "banner banner-info"; $("videoMetaBar").classList.remove("hidden");
  $("btnStartVideo").disabled = true;
  try {
    const res = await apiFetch("/api/videos/upload", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      $("videoMetaBar").textContent = data.detail || "Upload failed.";
      $("videoMetaBar").className = "banner banner-error"; return;
    }
    state.uploadId = data.upload_id;
    state.uploadPreview = data.preview_image || "";
    $("videoMetaBar").innerHTML = `✅ <strong>${data.filename}</strong> &nbsp;|&nbsp; Duration: <strong>${fmtDuration(data.duration_sec)}</strong> &nbsp;|&nbsp; <strong>${data.width}×${data.height}</strong> @${Math.round(data.fps)}fps &nbsp;|&nbsp; <strong>${data.size_mb} MB</strong>`;
    $("btnStartVideo").disabled = false; $("btnVideoPdf").classList.add("hidden");
    $("videoStatus").textContent = "File Ready"; $("videoStatus").className = "badge badge-low";

    $("videoAnalysisPanel").classList.remove("hidden");
    $("videoEventList").innerHTML = "";
    $("videoTimelineTrack").innerHTML = `<div class="timeline-line"></div>`;
    $("videoProgressFill").style.width = "0%";
    $("vidPeople").textContent = "0"; $("vidEvents").textContent = "0";
    $("vidPhones").textContent = "0"; $("vidMaxRisk").textContent = "Low";
    $("vidMaxRisk").className = "kpi-value";
    if (state.uploadPreview) {
      $("videoStreamImg").src = `data:image/jpeg;base64,${state.uploadPreview}`;
      $("videoStreamImg").classList.remove("hidden");
      $("videoStagePlaceholder").classList.add("hidden");
      $("videoProgressText").textContent = "Preview loaded — click ▶ Start Analysis to run AI detection.";
    } else {
      $("videoStreamImg").classList.add("hidden");
      $("videoStagePlaceholder").textContent = "Video uploaded — click ▶ Start Analysis";
      $("videoStagePlaceholder").classList.remove("hidden");
      $("videoProgressText").textContent = "Ready to analyse.";
    }
  } catch (err) {
    $("videoMetaBar").textContent = `Upload error: ${err.message || "Network error"}`;
    $("videoMetaBar").className = "banner banner-error";
  }
});

$("btnStartVideo").addEventListener("click", () => {
  if (!state.uploadId) return;
  let analysisDone = false;
  $("videoAnalysisPanel").classList.remove("hidden");
  $("videoEventList").innerHTML = "";
  $("videoTimelineTrack").innerHTML = `<div class="timeline-line"></div>`;
  $("videoProgressFill").style.width = "0%";
  $("videoProgressText").textContent = "Connecting to AI engine...";
  $("vidPeople").textContent = "0"; $("vidEvents").textContent = "0";
  $("vidPhones").textContent = "0"; $("vidMaxRisk").textContent = "Low";
  $("vidMaxRisk").className = "kpi-value";
  $("btnStartVideo").disabled = true;
  $("btnVideoPdf").classList.add("hidden");
  $("videoStatus").textContent = "Analysing..."; $("videoStatus").className = "badge badge-medium";
  if (state.uploadPreview) {
    $("videoStreamImg").src = `data:image/jpeg;base64,${state.uploadPreview}`;
    $("videoStreamImg").classList.remove("hidden");
    $("videoStagePlaceholder").classList.add("hidden");
  } else {
    $("videoStreamImg").classList.add("hidden");
    $("videoStagePlaceholder").textContent = "Loading AI models & starting video...";
    $("videoStagePlaceholder").classList.remove("hidden");
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({
    token: state.token,
    frame_skip: $("rngSkip").value,
    confidence: $("rngConf").value,
    cooldown: $("rngCooldown").value,
  });
  const ws = new WebSocket(`${proto}://${location.host}/ws/analyze-video/${state.uploadId}?${params}`);

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "status") {
      $("videoProgressText").textContent = msg.message || "Preparing AI pipeline...";
    } else if (msg.type === "started") {
      state.lastVideoSessionId = msg.session_id;
      $("videoProgressText").textContent = `Session #${msg.session_id} started — scanning frames...`;
    } else if (msg.type === "frame") {
      $("videoStagePlaceholder").classList.add("hidden");
      $("videoStreamImg").classList.remove("hidden");
      $("videoStreamImg").src = `data:image/jpeg;base64,${msg.image}`;
      $("videoProgressFill").style.width = `${msg.progress}%`;
      $("videoProgressText").textContent = `${msg.progress}% — ${fmtDuration(msg.timestamp_sec)}`;
      $("vidPeople").textContent = msg.people;
      $("vidEvents").textContent = msg.events_count;
      $("vidPhones").textContent = msg.phones_found;
      $("vidMaxRisk").textContent = msg.max_risk;
      $("vidMaxRisk").className = `kpi-value${msg.max_risk==="Low"?"":" alert"}`;
      msg.new_events.forEach(ev => {
        const cls = ev.risk_level==="High" ? "alert-card high" : "alert-card";
        const dotCls = String(ev.risk_level || "low").toLowerCase();
        const leftPct = Math.min(99, Math.max(1, Number(msg.progress) || 0));
        $("videoTimelineTrack").insertAdjacentHTML("beforeend",
          `<span class="timeline-dot ${escapeHtml(dotCls)}" style="left:${leftPct}%" title="${fmtDuration(ev.timestamp_sec)} — ${escapeHtml(ev.category)} (${escapeHtml(ev.risk_level)})"></span>`);
        $("videoEventList").insertAdjacentHTML("afterbegin",
          `<div class="${cls}"><strong>${escapeHtml(ev.category)}</strong><div class="alert-meta">Person ${ev.track_id} · ${fmtDuration(ev.timestamp_sec)} · ${riskBadge(ev.risk_level)} (${ev.risk_score})</div></div>`);
      });
    } else if (msg.type === "completed") {
      analysisDone = true;
      state.lastVideoSessionId = msg.session_id;
      $("videoProgressFill").style.width = "100%";
      $("videoProgressText").textContent = `✅ Completed — ${msg.events_count} event(s) flagged`;
      $("vidPeople").textContent = msg.people;
      $("vidEvents").textContent = msg.events_count;
      $("vidMaxRisk").textContent = msg.max_risk;
      $("vidMaxRisk").className = `kpi-value${msg.max_risk==="Low"?"":" alert"}`;
      $("btnStartVideo").disabled = false;
      $("btnVideoPdf").classList.remove("hidden");
      $("videoStatus").textContent = "Complete"; $("videoStatus").className = "badge badge-low";
      loadDashboard();
    } else if (msg.type === "error") {
      analysisDone = true;
      $("videoProgressText").textContent = `Error: ${msg.message}`;
      $("btnStartVideo").disabled = false;
      $("videoStatus").textContent = "Error"; $("videoStatus").className = "badge badge-high";
    }
  };
  ws.onerror = () => {
    if (!analysisDone) {
      $("videoProgressText").textContent = "WebSocket error while running video analysis.";
      $("btnStartVideo").disabled = false;
      $("videoStatus").textContent = "Error"; $("videoStatus").className = "badge badge-high";
    }
  };
  ws.onclose = () => {
    if (!analysisDone) {
      $("videoProgressText").textContent = "Connection interrupted before analysis finished. Please retry (try increasing frame skip for faster scan).";
      $("btnStartVideo").disabled = false;
      $("videoStatus").textContent = "Disconnected"; $("videoStatus").className = "badge badge-high";
    }
  };
});

$("btnVideoPdf").addEventListener("click", () => {
  if (state.lastVideoSessionId)
    window.open(`/api/reports/${state.lastVideoSessionId}/pdf?token=${encodeURIComponent(state.token)}`, "_blank");
});

// ══════════ LIVE CAMERA ══════════
document.querySelectorAll(".cam-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".cam-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    state.camMode = tab.dataset.cam;
    $("camIpPanel").classList.toggle("hidden", state.camMode !== "ip");
    $("camBrowserPanel").classList.toggle("hidden", state.camMode !== "browser");
  });
});

$("btnPreviewBrowser").addEventListener("click", async () => {
  try {
    const devId = $("cameraSelect").value;
    const constraints = { video: devId ? { deviceId: { exact: devId } } : true, audio: false };
    state.liveStream = await navigator.mediaDevices.getUserMedia(constraints);
    $("livePreviewVideo").srcObject = state.liveStream;
    $("livePreviewVideo").classList.remove("hidden");
    $("liveStagePlaceholder").classList.add("hidden");
  } catch (err) {
    alert("Camera access denied: " + err.message);
  }
});

function initLivePage() {
  if (navigator.mediaDevices) {
    navigator.mediaDevices.enumerateDevices().then(devices => {
      const cams = devices.filter(d => d.kind === "videoinput");
      $("cameraSelect").innerHTML = cams.map((c,i) =>
        `<option value="${c.deviceId}">${c.label || `Camera ${i+1}`}</option>`).join("");
    }).catch(() => {});
  }
}

$("btnStartLive").addEventListener("click", async () => {
  $("btnStartLive").disabled = true;
  $("btnStopLive").disabled = false;
  $("liveAlertFeed").innerHTML = `<div style="color:var(--text-muted);font-size:0.84rem;">Connecting to camera and loading AI models...</div>`;
  $("liveStatusPill").textContent = "Connecting...";
  $("liveStatusPill").className = "badge badge-medium";
  $("liveStagePlaceholder").classList.add("hidden");

  const proto = location.protocol === "https:" ? "wss" : "ws";

  if (state.camMode === "ip") {
    // ─ IP Camera: server-side OpenCV reads the stream ─
    const rawUrl = $("camUrlInput").value.trim();
    if (!rawUrl) {
      $("liveStagePlaceholder").classList.remove("hidden");
      alert("Please enter an IP / RTSP / HTTP camera stream URL.");
      stopLiveMonitoring();
      return;
    }
    const camUrl = encodeURIComponent(rawUrl);
    $("liveAnnotatedImg").classList.remove("hidden");
    const ws = new WebSocket(`${proto}://${location.host}/ws/ip-camera?token=${encodeURIComponent(state.token)}&cam_url=${camUrl}`);
    state.liveWs = ws;
    ws.onmessage = evt => handleLiveMessage(JSON.parse(evt.data));
    ws.onerror = () => handleLiveMessage({ type: "error", message: "WebSocket connection error while connecting to camera stream." });
    ws.onclose = () => stopLiveMonitoring();

  } else {
    // ─ Browser WebRTC: capture canvas frames and send ─
    if (!state.liveStream) {
      try {
        state.liveStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      } catch (err) {
        $("liveStagePlaceholder").classList.remove("hidden");
        alert("Camera access denied: " + err.message); stopLiveMonitoring(); return;
      }
    }
    const videoEl = $("livePreviewVideo");
    videoEl.srcObject = state.liveStream;
    videoEl.classList.remove("hidden", "sr-video");
    $("liveAnnotatedImg").classList.add("hidden");

    const ws = new WebSocket(`${proto}://${location.host}/ws/live-webcam?token=${encodeURIComponent(state.token)}`);
    state.liveWs = ws;
    const canvas = $("liveCaptureCanvas");
    const ctx = canvas.getContext("2d");
    ws.onopen = () => {
      state.liveTimer = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN || !videoEl.videoWidth) return;
        canvas.width = 640; canvas.height = Math.round((videoEl.videoHeight / videoEl.videoWidth) * 640);
        ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
        ws.send(canvas.toDataURL("image/jpeg", 0.70));
      }, 230);
    };
    ws.onmessage = evt => handleLiveMessage(JSON.parse(evt.data));
    ws.onerror = () => handleLiveMessage({ type: "error", message: "WebSocket connection failed during live capture." });
    ws.onclose = () => stopLiveMonitoring();
  }
});

function handleLiveMessage(msg) {
  if (msg.type === "started") {
    $("liveAlertFeed").innerHTML = `<div style="color:var(--text-muted);font-size:0.84rem;">Connected (Session #${msg.session_id}). Monitoring active...</div>`;
    $("liveStatusPill").innerHTML = `<span class="live-dot"></span>LIVE`;
    $("liveStatusPill").className = "badge badge-high";
    return;
  }
  if (msg.type === "error") {
    const safeMsg = escapeHtml(msg.message);
    $("liveAnnotatedImg").classList.add("hidden");
    $("liveStagePlaceholder").classList.remove("hidden");
    $("liveStagePlaceholder").innerHTML = `<span style="color:#f87171;">⚠️ ${safeMsg}</span>`;
    $("liveAlertFeed").insertAdjacentHTML("afterbegin",
      `<div class="alert-card high"><strong>Connection Error</strong><div class="alert-meta">${safeMsg}</div></div>`);
    return;
  }
  if (msg.type === "frame") {
    if (!$("livePreviewVideo").classList.contains("hidden")) {
      $("livePreviewVideo").classList.add("sr-video");
    }
    $("liveAnnotatedImg").classList.remove("hidden");
    $("liveAnnotatedImg").src = `data:image/jpeg;base64,${msg.image}`;
    $("livePeople").textContent = msg.people_in_view ?? msg.people ?? 0;
    $("liveAlertsCount").textContent = msg.total_events ?? 0;
    $("liveMaxRisk").textContent = msg.max_risk ?? "Low";
    $("liveEvidenceCount").textContent = msg.evidence_saved ?? 0;
    (msg.new_events || []).forEach(ev => {
      const cls = ev.risk_level === "High" ? "alert-card high" : "alert-card";
      $("liveAlertFeed").insertAdjacentHTML("afterbegin",
        `<div class="${cls}"><strong>${ev.category}</strong><div class="alert-meta">Person ${ev.track_id} · ${fmtDuration(ev.timestamp_sec)} · ${riskBadge(ev.risk_level)} (${ev.risk_score})</div></div>`);
    });
  }
}

function stopLiveMonitoring() {
  if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer = null; }
  if (state.liveWs) {
    try { if (state.liveWs.readyState === WebSocket.OPEN) state.liveWs.send("__STOP__"); state.liveWs.close(); } catch (_) {}
    state.liveWs = null;
  }
  const startBtn = $("btnStartLive"); if (startBtn) startBtn.disabled = false;
  const stopBtn = $("btnStopLive"); if (stopBtn) stopBtn.disabled = true;
  const pill = $("liveStatusPill");
  if (pill) { pill.textContent = "Stopped"; pill.className = "badge badge-low"; }
}
$("btnStopLive").addEventListener("click", () => {
  stopLiveMonitoring();
  $("livePreviewVideo").classList.remove("sr-video");
  $("livePreviewVideo").classList.add("hidden");
  $("liveAnnotatedImg").classList.add("hidden");
  $("liveStagePlaceholder").classList.remove("hidden");
});

// ══════════ REPORTS ══════════
function clearSessionReportView() {
  $("repMode").textContent = "—";
  $("repDuration").textContent = "00:00:00";
  $("repEvents").textContent = "0";
  $("repRisk").textContent = "Low";
  $("repCategoryBars").innerHTML = `<p style="color:var(--text-muted);font-size:0.86rem;">No session selected.</p>`;
  $("repEvidenceGrid").innerHTML = `<p style="color:var(--text-muted);font-size:0.84rem;">No screenshots saved.</p>`;
  $("repEventTableBody").innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">No events found.</td></tr>`;
}

async function loadSessionsList(preferredId = null) {
  const res = await apiFetch("/api/sessions");
  const data = await res.json();
  const sel = $("reportSessionSelect");
  if (!data.sessions.length) {
    sel.innerHTML = `<option value="">No sessions recorded yet</option>`;
    $("btnDownloadPdf").disabled = true;
    $("btnDeleteSession").disabled = true;
    clearSessionReportView();
    return;
  }
  $("btnDownloadPdf").disabled = false;
  $("btnDeleteSession").disabled = false;
  sel.innerHTML = data.sessions.map(s =>
    `<option value="${s.id}">Session #${s.id} — ${escapeHtml(s.source_name)} [${escapeHtml(String(s.mode).toUpperCase())}] — ${escapeHtml(s.start_time)}</option>`).join("");
  if (preferredId && data.sessions.some(s => String(s.id) === String(preferredId))) {
    sel.value = String(preferredId);
  }
  await loadSessionDetail(sel.value);
}

$("btnLoadSession").addEventListener("click", () => {
  const sid = $("reportSessionSelect").value; if (sid) loadSessionDetail(sid);
});

$("btnDeleteSession").addEventListener("click", () => {
  const sid = $("reportSessionSelect").value;
  if (sid) deleteSessionRecord(sid, () => loadSessionsList());
});

async function loadSessionDetail(sessionId) {
  const res = await apiFetch(`/api/sessions/${sessionId}`);
  const data = await res.json();
  const s = data.session; const events = data.events;
  $("repMode").textContent = s.mode.toUpperCase();
  $("repDuration").textContent = fmtDuration(s.duration_sec);
  $("repEvents").textContent = events.length;
  $("repRisk").textContent = s.max_risk;

  const counts = {};
  events.forEach(e => counts[e.category] = (counts[e.category]||0) + 1);
  const maxCnt = Math.max(1, ...Object.values(counts));
  $("repCategoryBars").innerHTML = Object.keys(counts).length
    ? Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([cat,cnt]) => `
        <div class="stat-bar">
          <div class="stat-bar-label"><span>${escapeHtml(cat)}</span><strong>${cnt}</strong></div>
          <div class="stat-bar-track"><div class="stat-bar-fill" style="width:${(cnt/maxCnt)*100}%"></div></div>
        </div>`).join("")
    : `<p style="color:var(--text-muted);font-size:0.86rem;">No events in this session.</p>`;

  const shots = events.filter(e => e.screenshot_url);
  if (shots.length) {
    $("repEvidenceGrid").innerHTML = shots.map(e => `
      <div class="evidence-thumb">
        <a href="${escapeHtml(e.screenshot_url)}" target="_blank" title="Open full screenshot">
          <img src="${escapeHtml(e.screenshot_url)}" alt="Evidence"/>
          <div class="cap">${fmtDuration(e.timestamp_sec)} · ${escapeHtml(e.category)} (P${e.track_id})</div>
        </a>
      </div>`).join("");
  } else if (data.snapshot_url) {
    $("repEvidenceGrid").innerHTML = `
      <div class="evidence-thumb">
        <a href="${escapeHtml(data.snapshot_url)}" target="_blank" title="Open session snapshot">
          <img src="${escapeHtml(data.snapshot_url)}" alt="Session Snapshot"/>
          <div class="cap">Session Snapshot (No cheating flagged)</div>
        </a>
      </div>`;
  } else {
    $("repEvidenceGrid").innerHTML = `<p style="color:var(--text-muted);font-size:0.84rem;">No screenshots saved.</p>`;
  }

  $("repEventTableBody").innerHTML = events.length
    ? events.map(e => `
        <tr>
          <td>${fmtDuration(e.timestamp_sec)}</td>
          <td>${escapeHtml(e.category)}</td>
          <td>Person ${e.track_id}</td>
          <td>${e.risk_score}</td>
          <td>${riskBadge(e.risk_level)}</td>
          <td>${e.screenshot_url ? `<a class="mini-shot-link" href="${escapeHtml(e.screenshot_url)}" target="_blank">View Shot</a>` : "—"}</td>
          <td><button class="btn btn-danger btn-xs" onclick="deleteEventRecord(${e.id}, () => loadSessionDetail(${sessionId}))">🗑 Delete</button></td>
        </tr>`).join("")
    : `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:16px;">No events found.</td></tr>`;
}

$("btnDownloadPdf").addEventListener("click", () => {
  const sid = $("reportSessionSelect").value;
  if (sid) openSessionPdf(sid);
});

// ══════════ PRIVILEGED ACCOUNTS & REPORTS CONSOLE ══════════
async function loadManagementConsole() {
  if (!(state.user && state.user.is_admin)) return;
  try {
    const res = await apiFetch("/api/admin/overview");
    if (!res.ok) return;
    const data = await res.json();
    $("mgmtTotalAccounts").textContent = data.total_accounts;
    $("mgmtVerifiedAccounts").textContent = data.verified_accounts;
    $("mgmtTotalSessions").textContent = data.total_sessions;
    $("mgmtTotalEvents").textContent = data.total_events;

    const abody = $("mgmtAccountsBody");
    if (!data.accounts.length) {
      abody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:16px;">No registered accounts yet.</td></tr>`;
    } else {
      abody.innerHTML = data.accounts.map((u, idx) => `
        <tr>
          <td>${idx + 1}</td>
          <td>${escapeHtml(u.full_name)}</td>
          <td>${escapeHtml(u.email)}</td>
          <td>${escapeHtml(u.campus || "—")}</td>
          <td>${u.is_verified ? `<span class="badge badge-low">Verified</span>` : `<span class="badge badge-medium">Pending</span>`}</td>
          <td>${u.sessions_count}</td>
          <td>${u.events_count}</td>
          <td>${escapeHtml(u.created_at)}</td>
          <td><button class="btn btn-danger btn-xs" onclick="deleteUserAccount(${u.id})">🗑 Delete</button></td>
        </tr>`).join("");
    }

    const rbody = $("mgmtReportsBody");
    if (!data.reports.length) {
      rbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:16px;">No monitoring reports recorded yet.</td></tr>`;
    } else {
      rbody.innerHTML = data.reports.map(r => `
        <tr>
          <td>#${r.id}</td>
          <td>${escapeHtml(r.user_email || "—")}</td>
          <td>${escapeHtml(r.effective_campus || "—")}</td>
          <td>${escapeHtml(String(r.mode || "").toUpperCase())}</td>
          <td style="max-width:170px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(r.source_name)}</td>
          <td>${r.total_events} (${r.screenshot_count} shots)</td>
          <td>${riskBadge(r.max_risk)}</td>
          <td style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-outline btn-xs" onclick="openReportSession(${r.id})">View</button>
            <button class="btn btn-gold btn-xs" onclick="openSessionPdf(${r.id})">⬇ PDF</button>
            <button class="btn btn-danger btn-xs" onclick="deleteSessionRecord(${r.id}, loadManagementConsole)">🗑 Delete</button>
          </td>
        </tr>`).join("");
    }
  } catch (_) {}
}

async function deleteUserAccount(userId) {
  if (!confirm("Delete this registered account?")) return;
  const res = await apiFetch(`/api/admin/users/${userId}`, { method: "DELETE" });
  if (res.ok) {
    await loadManagementConsole();
  } else {
    const data = await res.json();
    alert(data.detail || "Could not delete account.");
  }
}

function showPwBanner(msg, type = "info") {
  const el = $("pwBanner");
  el.className = `banner banner-${type}`;
  el.textContent = msg;
  el.classList.remove("hidden");
}

$("changePasswordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const curPw = $("curPassword").value;
  const newPw = $("newPassword").value;
  const confPw = $("confirmNewPassword").value;
  if (newPw !== confPw) {
    showPwBanner("New passwords do not match.", "error");
    return;
  }
  const res = await apiFetch("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: curPw, new_password: newPw }),
  });
  const data = await res.json();
  if (data.success) {
    showPwBanner(data.message, "success");
    $("changePasswordForm").reset();
  } else {
    showPwBanner(data.message || "Failed to update password.", "error");
  }
});

// ══════════ BOOT ══════════
(async () => {
  if (!state.token) return;
  try {
    const res = await apiFetch("/api/auth/me");
    const data = await res.json();
    enterPortal(data.user);
  } catch (_) { logoutLocal(); }
})();
