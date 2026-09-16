const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── Health check ──────────────────────────────────────────
async function pingHealth() {
  const dot = $("#health-dot"), txt = $("#health-text");
  try {
    const r = await fetch("/api/health");
    if (!r.ok) throw new Error("bad status");
    dot.classList.add("on"); dot.classList.remove("off");
    txt.textContent = "connected";
  } catch {
    dot.classList.add("off"); dot.classList.remove("on");
    txt.textContent = "offline";
  }
}
setInterval(pingHealth, 15000); pingHealth();

// ── Tabs ──────────────────────────────────────────────────
$$(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach(t => t.classList.remove("active"));
    $$(".panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    $("#panel-" + tab.dataset.tab).classList.add("active");
  });
});

// ── Helpers ───────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
}[c]));

function card(html, kind="") {
  return `<div class="card ${kind}">${html}</div>`;
}

function renderPlayer(p, did) {
  if (!p) return card("No player data", "error");
  const sb = p.skin_breakdown || {};
  return card(`
<b>DEVICE ID CHECK RESULT</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
🎮 Acc    : ${esc(p.player_id || "?")}
🌐 Zone   : ${esc(p.server || "?")}
🏷 Nick   : ${esc(p.nickname || "N/A")}
📈 Level  : ${esc(p.level || "N/A")}
🦸 Heroes : ${esc(p.hero_count || 0)}
🎨 Skins  : ${esc(p.skin_count || 0)}

<b>RANKS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 Current: ${esc(p.current_rank || "Unranked")}
⭐ High   : ${esc(p.high_rank || "N/A")}
💠 Collector: ${esc(p.collector_tier || "None")}
💎 Points : ${esc(p.collector_point || 0)}

<b>SKIN BREAKDOWN</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 Supreme    : ${sb["Supreme Skins"] || 0}
🟣 Grand      : ${sb["Grand Skins"] || 0}
🟡 Exquisite  : ${sb["Exquisite Skins"] || 0}
🔵 Deluxe     : ${sb["Deluxe Skins"] || 0}
🟢 Exceptional: ${sb["Exceptional Skins"] || 0}
⚪ Common     : ${sb["Common Skins"] || 0}

<b>ACCOUNT</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 Loc    : ${esc(p.location || "NOT FOUND")}
⏰ Login  : ${esc(p.last_login || "N/A")}
📅 Created: ${esc(p.creation_date || "N/A")}
⌛ Age    : ${esc(p.account_age || "N/A")}
👥 Squad  : ${esc(p.squad || "—")}
🎯 WR     : ${esc(p.win_rate || "N/A")}
⚔ Battles: ${esc(p.total_battles || 0)}
💛 Affinity: ${esc(p.affinity || "None")}
⭐ Starlight: ${esc(p.starlight_user || "No")}
🛡 Credits : ${esc(p.credits_score || "N/A")}
🚨 Flags   : ${esc(p.restriction_flags || "None")}
🦸 Recent  : ${esc((p.hero_history || []).slice(0,5).join(", ") || "N/A")}
`, "ok");
}

function renderBan(ban, did) {
  if (!ban) return card("No ban data", "error");
  const s = ban.state || "clear";
  if (s === "banned") {
    return card(`
<b>🚫 BANNED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device  : ${esc(did)}
📝 Reason  : ${esc(ban.reason || "?")}
🔢 Code    : ${esc(ban.reason_raw || "?")}
⏱ Duration: ${esc(ban.remaining || "?")}
`, "error");
  }
  if (s === "unknown") {
    return card(`
<b>⚠️ UNKNOWN</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
📝 Detail : ${esc(ban.label || "no 20001 response")}
`, "warn");
  }
  if (s === "unregistered") {
    return card(`
<b>❌ UNREGISTERED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
`, "warn");
  }
  return card(`
<b>✅ NOT BANNED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
`, "ok");
}

// ── Single check ──────────────────────────────────────────
$("#single-btn").addEventListener("click", async () => {
  const did = $("#single-input").value.trim();
  const out = $("#single-output");
  if (!did) { out.innerHTML = card("Enter a device ID", "error"); return; }
  out.innerHTML = card("⏳ Checking…");
  try {
    const r = await fetch("/api/check/single", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ device_id: did })
    });
    const data = await r.json();
    if (data.result?.status === "success") {
      out.innerHTML = renderPlayer(data.result.player_data, did);
    } else {
      out.innerHTML = card(`❌ <b>Check failed</b>\n${esc(data.result?.error || data.error || "unknown")}`, "error");
    }
  } catch (e) {
    out.innerHTML = card("Network error: " + e.message, "error");
  }
});

// ── Ban single ────────────────────────────────────────────
$("#ban-btn").addEventListener("click", async () => {
  const did = $("#ban-input").value.trim();
  const out = $("#ban-output");
  if (!did) { out.innerHTML = card("Enter a device ID", "error"); return; }
  out.innerHTML = card("⏳ Checking ban status… (up to 25s)");
  try {
    const r = await fetch("/api/ban/single", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ device_id: did })
    });
    const data = await r.json();
    if (data.result?.status === "success") {
      out.innerHTML = renderBan(data.result.ban, did);
    } else {
      out.innerHTML = card(`❌ <b>Ban check failed</b>\n${esc(data.result?.error || data.error || "unknown")}`, "error");
    }
  } catch (e) {
    out.innerHTML = card("Network error: " + e.message, "error");
  }
});

// ── Generate ─────────────────────────────────────────────
let genIds = [];
$("#gen-btn").addEventListener("click", async () => {
  const count = parseInt($("#gen-count").value || "10", 10);
  const out = $("#gen-output");
  out.textContent = "⏳ Generating…";
  $("#gen-copy").disabled = true;
  try {
    const r = await fetch("/api/generate", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ count })
    });
    const data = await r.json();
    if (!data.ok) { out.textContent = "Error: " + (data.error || "unknown"); return; }
    genIds = data.ids || [];
    out.textContent = genIds.join("\n");
    $("#gen-copy").disabled = genIds.length === 0;
  } catch (e) {
    out.textContent = "Network error: " + e.message;
  }
});
$("#gen-copy").addEventListener("click", async () => {
  if (!genIds.length) return;
  try { await navigator.clipboard.writeText(genIds.join("\n")); alert("Copied " + genIds.length + " IDs"); }
  catch { alert("Copy failed"); }
});

// ── Bulk worker helpers ──────────────────────────────────
function makeBulkController(cfg) {
  let jobId = null;
  let pollTimer = null;

  const $inp    = $(cfg.inputSel);
  const $thread = $(cfg.threadSel);
  const $start  = $(cfg.startSel);
  const $stop   = $(cfg.stopSel);
  const $dl     = $(cfg.dlSel);
  const $wrap   = $(cfg.progressSel);
  const $bar    = $(cfg.barSel);
  const $stats  = cfg.statsMap;
  const $latest = $(cfg.latestSel);

  async function start() {
    const ids = $inp.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (!ids.length) { alert("Enter at least one device ID"); return; }
    const threads = parseInt($thread.value || "30", 10);
    $start.disabled = true; $stop.disabled = false; $dl.disabled = true;
    $wrap.classList.remove("hidden");
    $bar.style.width = "0%";
    Object.values($stats).forEach(el => el.textContent = "0");
    $latest.innerHTML = "";

    try {
      const r = await fetch("/api/bulk/start", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ kind: cfg.kind, ids: ids.join("\n"), threads })
      });
      const data = await r.json();
      if (!data.ok) { alert("Start failed: " + (data.error || "?")); $start.disabled = false; $stop.disabled = true; return; }
      jobId = data.job_id;
      pollTimer = setInterval(poll, 1200);
      poll();
    } catch (e) {
      alert("Network error: " + e.message);
      $start.disabled = false; $stop.disabled = true;
    }
  }

  async function poll() {
    if (!jobId) return;
    try {
      const r = await fetch("/api/bulk/status/" + jobId);
      const data = await r.json();
      const j = data.job;
      if (!j || j.error) return;
      render(j);
      if (j.done) {
        clearInterval(pollTimer);
        $start.disabled = false; $stop.disabled = true; $dl.disabled = false;
      }
    } catch {}
  }

  function render(j) {
    $bar.style.width = (j.pct || 0).toFixed(1) + "%";
    $(cfg.totalSel).textContent    = j.total;
    $(cfg.checkedSel).textContent  = j.checked;
    for (const [key, sel] of Object.entries($stats)) {
      $(sel).textContent = j[key] ?? 0;
    }
    const items = (j.latest || []).slice(-8).reverse();
    $latest.innerHTML = items.map(it => {
      const cls = it.state || "valid";
      let info = "";
      if (it.state === "valid") info = `${esc(it.nickname || "?")} Lv${it.level} 🎨${it.skins}`;
      else if (it.state === "filtered") info = `Filtered Lv${it.level}`;
      else if (it.state === "banned") info = `🚫 ${esc(it.reason || "Banned")} · ${esc(it.remaining || "")}`;
      else if (it.state === "clean") info = "Not Banned";
      else if (it.state === "unregistered") info = "Unregistered";
      else if (it.state === "unknown") info = esc(it.error || "Unknown");
      else info = esc(it.error || "Invalid");
      return `<div class="line ${cls}">
        <span class="tag">${esc(it.device_id?.slice(-12) || "?")}</span>
        <span>${info}</span>
      </div>`;
    }).join("");
  }

  async function stop() {
    if (!jobId) return;
    try { await fetch("/api/bulk/stop/" + jobId, { method: "POST" }); } catch {}
  }

  function download() {
    if (!jobId) return;
    window.location = "/api/bulk/download/" + jobId;
  }

  $start.addEventListener("click", start);
  $stop.addEventListener("click", stop);
  $dl.addEventListener("click", download);
}

makeBulkController({
  kind: "check",
  inputSel: "#bulk-input",
  threadSel: "#bulk-threads",
  startSel: "#bulk-start",
  stopSel: "#bulk-stop",
  dlSel: "#bulk-dl",
  progressSel: "#bulk-progress",
  barSel: "#bulk-bar",
  totalSel: "#st-total",
  checkedSel: "#st-checked",
  latestSel: "#bulk-latest",
  statsMap: {
    registered: "#st-reg",
    unregistered: "#st-unreg",
    invalid: "#st-inv",
    valid: "#st-valid",
  },
});

makeBulkController({
  kind: "ban",
  inputSel: "#banbulk-input",
  threadSel: "#banbulk-threads",
  startSel: "#banbulk-start",
  stopSel: "#banbulk-stop",
  dlSel: "#banbulk-dl",
  progressSel: "#banbulk-progress",
  barSel: "#banbulk-bar",
  totalSel: "#bst-total",
  checkedSel: "#bst-checked",
  latestSel: "#banbulk-latest",
  statsMap: {
    banned: "#bst-banned",
    clean: "#bst-clean",
    unregistered: "#bst-unreg",
    invalid: "#bst-inv",
  },
});

// ── Kick ─────────────────────────────────────────────────
let kickTimer = null;
function renderKick(s, did) {
  const running = s.status === "running" || s.status === "fetching";
  const tag = s.status === "error" ? "❌ ERROR"
            : s.status === "fetching" ? "🔍 FETCHING PROFILE"
            : running ? "🟢 RUNNING"
            : "✅ FINISHED";
  return `
<b>⚡ BRUTEFORCE KICKER — ${tag}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device   : ${esc(did || "?")}
👤 Target   : ${esc(s.nickname || "?")}
🎮 Acc ID   : ${esc(s.account_id || "?")}
🌐 GameSrv  : ${esc(s.gs_info || "?")}
🔄 Attempts : ${s.attempts || 0}
✅ Hits     : ${s.hits || 0}
❌ Fails    : ${s.fails || 0}
⚡ Avg Lat  : ${(s.avg_latency || 0).toFixed(0)}ms
⏱ Elapsed  : ${((s.elapsed || 0)).toFixed(0)}s
⏳ Delay    : 3.0s / attempt
${s.error ? "\n⚠️ Error: " + esc(s.error) : ""}
`;
}
$("#kick-start").addEventListener("click", async () => {
  const did = $("#kick-input").value.trim();
  const out = $("#kick-panel");
  out.classList.remove("hidden");
  if (!did) { out.innerHTML = card("Enter a device ID", "error"); return; }
  $("#kick-start").disabled = true; $("#kick-stop").disabled = false;
  out.innerHTML = card(renderKick({ status: "fetching" }, did), "warn");
  try {
    const r = await fetch("/api/kick/start", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ device_id: did })
    });
    const data = await r.json();
    if (!data.ok) { out.innerHTML = card("Error: " + esc(data.error || "?"), "error"); $("#kick-start").disabled = false; $("#kick-stop").disabled = true; return; }
    if (kickTimer) clearInterval(kickTimer);
    kickTimer = setInterval(async () => {
      // We do NOT have a per-kick status endpoint (kick runs in-thread).
      // Just leave the last render. Stop button still works.
    }, 5000);
  } catch (e) {
    out.innerHTML = card("Network error: " + esc(e.message), "error");
    $("#kick-start").disabled = false; $("#kick-stop").disabled = true;
  }
});
$("#kick-stop").addEventListener("click", () => {
  // Best-effort: notify user; real stop is server-side
  $("#kick-stop").disabled = true;
  $("#kick-start").disabled = false;
  if (kickTimer) { clearInterval(kickTimer); kickTimer = null; }
});
