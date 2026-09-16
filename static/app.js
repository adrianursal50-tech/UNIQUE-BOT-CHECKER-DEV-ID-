const $  = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const esc = s => String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const card = (h,k="")=>`<div class="card ${k}">${h}</div>`;
const fmt = n => (n||0).toLocaleString();

let STATE = { user: null, activeJob: null, pollTimer: null };

// ═════════════ VIEW SWITCHING ═════════════
function showView(v){
  $$(".view").forEach(x=>x.classList.add("hidden"));
  $("#view-"+v).classList.remove("hidden");
}

// ═════════════ AUTH ═════════════
$$(".auth-tab").forEach(t=>{
  t.addEventListener("click",()=>{
    $$(".auth-tab").forEach(x=>x.classList.remove("active"));
    $$(".auth-form").forEach(x=>x.classList.remove("active"));
    t.classList.add("active");
    $("#form-"+t.dataset.auth).classList.add("active");
  });
});

async function loadCaptcha(){
  try{
    const r = await fetch("/api/captcha");
    const d = await r.json();
    if(d.ok) $("#captcha-q").textContent = d.question + " = ?";
  }catch{ $("#captcha-q").textContent = "error"; }
}
$("#captcha-reload").addEventListener("click", loadCaptcha);

$("#form-signup").addEventListener("submit", async e=>{
  e.preventDefault();
  const f = e.target;
  const errBox = f.querySelector("[data-err]");
  errBox.textContent = "";
  const fd = new FormData(f);
  try{
    const r = await fetch("/api/auth/signup",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        username: fd.get("username"), password: fd.get("password"),
        captcha: fd.get("captcha")
      })
    });
    const d = await r.json();
    if(!d.ok){ errBox.textContent = d.error||"signup failed"; loadCaptcha(); return; }
    STATE.user = d.user;
    enterApp();
  }catch(e){ errBox.textContent = "network error"; }
});

$("#form-login").addEventListener("submit", async e=>{
  e.preventDefault();
  const f = e.target;
  const errBox = f.querySelector("[data-err]");
  errBox.textContent = "";
  const fd = new FormData(f);
  try{
    const r = await fetch("/api/auth/login",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username: fd.get("username"), password: fd.get("password")})
    });
    const d = await r.json();
    if(!d.ok){ errBox.textContent = d.error||"login failed"; return; }
    STATE.user = d.user;
    enterApp();
  }catch(e){ errBox.textContent = "network error"; }
});

$("#logout-btn").addEventListener("click", async ()=>{
  await fetch("/api/auth/logout",{method:"POST"});
  STATE.user = null;
  STATE.activeJob = null;
  localStorage.removeItem("active_job");
  location.reload();
});

$("#admin-btn").addEventListener("click", async ()=>{
  const pw = prompt("Admin password:");
  if(!pw) return;
  const r = await fetch("/api/admin/login",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({password: pw})
  });
  const d = await r.json();
  if(!d.ok){ alert("Wrong password"); return; }
  STATE.user.is_admin = true;
  showView("admin");
  loadAdminStats();
  loadAdminUsers();
});

$("#admin-back").addEventListener("click", ()=> showView("app"));

// ═════════════ APP INIT ═════════════
function enterApp(){
  showView("app");
  $("#my-name").textContent = STATE.user.username;
  $("#my-credits").textContent = fmt(STATE.user.credits);
  if(STATE.user.is_admin) $("#admin-btn").classList.remove("hidden");
  // resume job if any
  const saved = localStorage.getItem("active_job");
  if(saved) tryResume(saved);
}

async function refreshMe(){
  const r = await fetch("/api/auth/me");
  const d = await r.json();
  if(d.ok && d.user){
    STATE.user = d.user;
    $("#my-credits").textContent = fmt(d.user.credits);
    if(d.user.is_admin) $("#admin-btn").classList.remove("hidden");
  }
}

// ═════════════ TABS ═════════════
$$(".tab").forEach(t=>{
  t.addEventListener("click",()=>{
    $$(".tab").forEach(x=>x.classList.remove("active"));
    $$(".panel").forEach(x=>x.classList.remove("active"));
    t.classList.add("active");
    $("#panel-"+t.dataset.tab).classList.add("active");
    if(t.dataset.tab === "jobs") loadMyJobs();
  });
});

// ═════════════ SINGLE ═════════════
$("#single-btn").addEventListener("click", async ()=>{
  const did = $("#single-input").value.trim();
  const out = $("#single-output");
  if(!did){ out.innerHTML = card("Enter a device ID","error"); return; }
  out.innerHTML = card("⏳ Checking…");
  try{
    const r = await fetch("/api/check/single",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({device_id: did})
    });
    const d = await r.json();
    if(!d.ok){ out.innerHTML = card("❌ "+esc(d.error||"failed"),"error"); return; }
    if(d.result?.status === "success") out.innerHTML = renderPlayer(d.result.player_data, did);
    else out.innerHTML = card("❌ "+esc(d.result?.error||"unknown"),"error");
    refreshMe();
  }catch(e){ out.innerHTML = card("network error: "+esc(e.message),"error"); }
});

function renderPlayer(p,did){
  if(!p) return card("no data","error");
  const sb = p.skin_breakdown||{};
  return card(`
<b>✅ VALID</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
🎮 Acc    : ${esc(p.player_id||"?")}
🌐 Zone   : ${esc(p.server||"?")}
🏷 Nick   : ${esc(p.nickname||"N/A")}
📈 Level  : ${esc(p.level||"N/A")}
🦸 Heroes : ${esc(p.hero_count||0)}
🎨 Skins  : ${esc(p.skin_count||0)}

<b>RANKS</b>
🏆 Current: ${esc(p.current_rank||"Unranked")}
⭐ High   : ${esc(p.high_rank||"N/A")}
💠 Collector: ${esc(p.collector_tier||"None")}
💎 Points : ${esc(p.collector_point||0)}

<b>SKIN BREAKDOWN</b>
💎 Supreme: ${sb["Supreme Skins"]||0}  🟣 Grand: ${sb["Grand Skins"]||0}
🟡 Exquisite: ${sb["Exquisite Skins"]||0}  🔵 Deluxe: ${sb["Deluxe Skins"]||0}
🟢 Exceptional: ${sb["Exceptional Skins"]||0}  ⚪ Common: ${sb["Common Skins"]||0}

<b>ACCOUNT</b>
📍 Loc    : ${esc(p.location||"NOT FOUND")}
⏰ Login  : ${esc(p.last_login||"N/A")}
📅 Created: ${esc(p.creation_date||"N/A")}
⌛ Age    : ${esc(p.account_age||"N/A")}
👥 Squad  : ${esc(p.squad||"—")}
🎯 WR     : ${esc(p.win_rate||"N/A")}
⚔ Battles: ${esc(p.total_battles||0)}
💛 Affinity: ${esc(p.affinity||"None")}
⭐ Starlight: ${esc(p.starlight_user||"No")}
🚨 Flags   : ${esc(p.restriction_flags||"None")}
🦸 Recent  : ${esc((p.hero_history||[]).slice(0,5).join(", ")||"N/A")}
`,"ok");
}

// ═════════════ BAN SINGLE ═════════════
$("#ban-btn").addEventListener("click", async ()=>{
  const did = $("#ban-input").value.trim();
  const out = $("#ban-output");
  if(!did){ out.innerHTML = card("Enter a device ID","error"); return; }
  out.innerHTML = card("⏳ Checking ban (up to 25 s)…");
  try{
    const r = await fetch("/api/ban/single",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({device_id: did})
    });
    const d = await r.json();
    if(!d.ok){ out.innerHTML = card("❌ "+esc(d.error||"failed"),"error"); return; }
    out.innerHTML = renderBan(d.result?.ban, did);
    refreshMe();
  }catch(e){ out.innerHTML = card("network error: "+esc(e.message),"error"); }
});

function renderBan(ban,did){
  if(!ban) return card("no ban data","error");
  const s = ban.state||"clear";
  if(s==="banned") return card(`
<b>🚫 BANNED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device: ${esc(did)}
📝 Reason: ${esc(ban.reason||"?")}
🔢 Code  : ${esc(ban.reason_raw||"?")}
⏱ Time  : ${esc(ban.remaining||"?")}
`,"error");
  if(s==="unknown") return card(`
<b>⚠️ UNKNOWN</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device: ${esc(did)}
📝 Detail: ${esc(ban.label||"no response")}
`,"warn");
  if(s==="unregistered") return card(`
<b>❌ UNREGISTERED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device: ${esc(did)}
`,"warn");
  return card(`
<b>✅ NOT BANNED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device: ${esc(did)}
`,"ok");
}

// ═════════════ GENERATE ═════════════
let genIds = [];
$("#gen-btn").addEventListener("click", async ()=>{
  const count = parseInt($("#gen-count").value||"10",10);
  const out = $("#gen-output");
  out.textContent = "⏳…"; $("#gen-copy").disabled = true;
  try{
    const r = await fetch("/api/generate",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({count})
    });
    const d = await r.json();
    if(!d.ok){ out.textContent = "Error: "+(d.error||""); return; }
    genIds = d.ids||[]; out.textContent = genIds.join("\n");
    $("#gen-copy").disabled = genIds.length === 0;
  }catch(e){ out.textContent = "error: "+e.message; }
});
$("#gen-copy").addEventListener("click", async ()=>{
  if(!genIds.length) return;
  try{ await navigator.clipboard.writeText(genIds.join("\n")); alert("Copied "+genIds.length+" IDs"); }
  catch{ alert("Copy failed"); }
});

// ═════════════ BULK CONTROLLERS ═════════════
function makeBulk(cfg){
  const $inp=$(cfg.inputSel), $th=$(cfg.threadSel), $start=$(cfg.startSel),
        $stop=$(cfg.stopSel), $dl=$(cfg.dlSel), $wrap=$(cfg.progressSel),
        $bar=$(cfg.barSel), $latest=$(cfg.latestSel);

  async function start(){
    const ids = $inp.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(!ids.length){ alert("Enter at least one device ID"); return; }
    const threads = parseInt($th.value||"30",10);

    $start.disabled=true; $stop.disabled=false; $dl.disabled=true;
    $wrap.classList.remove("hidden"); $bar.style.width="0%";
    Object.values(cfg.statsMap).forEach(s=>$(s).textContent="0");
    $(cfg.totalSel).textContent = ids.length;
    $(cfg.checkedSel).textContent = "0";
    $latest.innerHTML = "";

    try{
      const r = await fetch("/api/bulk/start",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({kind: cfg.kind, ids: ids.join("\n"), threads})
      });
      const d = await r.json();
      if(!d.ok){
        alert("Start failed: "+(d.error||"?"));
        $start.disabled=false; $stop.disabled=true; return;
      }
      STATE.activeJob = d.job_id;
      localStorage.setItem("active_job", JSON.stringify({job_id: d.job_id, kind: cfg.kind}));
      refreshMe();
      if(STATE.pollTimer) clearInterval(STATE.pollTimer);
      STATE.pollTimer = setInterval(poll, 1500);
      poll();
    }catch(e){
      alert("Network error: "+e.message);
      $start.disabled=false; $stop.disabled=true;
    }
  }

  async function poll(){
    if(!STATE.activeJob) return;
    try{
      const r = await fetch("/api/bulk/status/"+STATE.activeJob);
      const d = await r.json();
      if(!d.ok) return;
      const j = d.job;
      render(j);
      if(j.done){
        clearInterval(STATE.pollTimer); STATE.pollTimer=null;
        $start.disabled=false; $stop.disabled=true; $dl.disabled=false;
      }
    }catch{}
  }

  function render(j){
    $bar.style.width = (j.pct||0).toFixed(1)+"%";
    $(cfg.totalSel).textContent = j.total;
    $(cfg.checkedSel).textContent = j.checked;
    for(const [k,sel] of Object.entries(cfg.statsMap)){
      $(sel).textContent = j[k]??0;
    }
    const items = (j.latest||[]).slice(-8).reverse();
    $latest.innerHTML = items.map(it=>{
      const cls = it.state||"valid";
      let info="";
      if(it.state==="valid") info = `${esc(it.nickname||"?")} Lv${it.level} 🎨${it.skins}`;
      else if(it.state==="filtered") info = `Filtered Lv${it.level}`;
      else if(it.state==="banned") info = `🚫 ${esc(it.reason||"Banned")} ${esc(it.remaining||"")}`;
      else if(it.state==="clean") info = "Not Banned";
      else if(it.state==="unregistered") info = "Unregistered";
      else if(it.state==="unknown") info = esc(it.error||"Unknown");
      else info = esc(it.error||"Invalid");
      return `<div class="line ${cls}">
        <span class="tag">…${esc(String(it.device_id||"").slice(-12))}</span>
        <span>${info}</span>
      </div>`;
    }).join("");
  }

  async function stop(){
    if(!STATE.activeJob) return;
    try{ await fetch("/api/bulk/stop/"+STATE.activeJob,{method:"POST"}); }catch{}
  }
  function download(){
    if(!STATE.activeJob) return;
    window.location = "/api/bulk/download/"+STATE.activeJob;
  }

  $start.addEventListener("click", start);
  $stop.addEventListener("click", stop);
  $dl.addEventListener("click", download);
}

makeBulk({
  kind:"check",
  inputSel:"#bulk-input", threadSel:"#bulk-threads",
  startSel:"#bulk-start", stopSel:"#bulk-stop", dlSel:"#bulk-dl",
  progressSel:"#bulk-progress", barSel:"#bulk-bar",
  totalSel:"#st-total", checkedSel:"#st-checked", latestSel:"#bulk-latest",
  statsMap:{registered:"#st-reg",unregistered:"#st-unreg",invalid:"#st-inv",valid:"#st-valid"}
});
makeBulk({
  kind:"ban",
  inputSel:"#banbulk-input", threadSel:"#banbulk-threads",
  startSel:"#banbulk-start", stopSel:"#banbulk-stop", dlSel:"#banbulk-dl",
  progressSel:"#banbulk-progress", barSel:"#banbulk-bar",
  totalSel:"#bst-total", checkedSel:"#bst-checked", latestSel:"#banbulk-latest",
  statsMap:{banned:"#bst-banned",clean:"#bst-clean",unregistered:"#bst-unreg",invalid:"#bst-inv"}
});

// ═════════════ KICK ═════════════
$("#kick-start").addEventListener("click", async ()=>{
  const did = $("#kick-input").value.trim();
  const out = $("#kick-panel");
  out.classList.remove("hidden");
  if(!did){ out.innerHTML = card("Enter a device ID","error"); return; }
  $("#kick-start").disabled = true;
  out.innerHTML = card("⚡ Starting kick…");
  try{
    const r = await fetch("/api/kick/start",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({device_id: did})
    });
    const d = await r.json();
    if(!d.ok){ out.innerHTML = card("❌ "+esc(d.error||"failed"),"error"); $("#kick-start").disabled=false; return; }
    out.innerHTML = card(`
<b>⚡ BRUTEFORCE KICKER — STARTED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 Device : ${esc(did)}
⏳ Delay  : 3 s per attempt
🔄 Rounds : 20
💡 Each round opens a fresh socket and re-sends the handshake.
   Target session is invalidated by every successful handshake.

Check back in ~1 minute.
`,"warn");
    refreshMe();
  }catch(e){ out.innerHTML = card("network error: "+esc(e.message),"error"); $("#kick-start").disabled=false; }
});

// ═════════════ RESUME / JOBS ═════════════
function tryResume(saved){
  try{
    const info = JSON.parse(saved);
    if(!info.job_id) return;
    STATE.activeJob = info.job_id;
    // Show the right panel
    const tabSel = info.kind === "ban" ? "banbulk" : "bulk";
    $$(".tab").forEach(t=>t.classList.remove("active"));
    $$(".panel").forEach(p=>p.classList.remove("active"));
    document.querySelector(`.tab[data-tab="${tabSel}"]`)?.classList.add("active");
    $("#panel-"+tabSel)?.classList.add("active");
    // Start polling
    const $wrap = info.kind === "ban" ? $("#banbulk-progress") : $("#bulk-progress");
    $wrap?.classList.remove("hidden");
    if(STATE.pollTimer) clearInterval(STATE.pollTimer);
    STATE.pollTimer = setInterval(()=>{
      fetch("/api/bulk/status/"+STATE.activeJob)
        .then(r=>r.json()).then(d=>{
          if(!d.ok) return;
          const j = d.job;
          if(info.kind === "ban"){
            $("#banbulk-bar").style.width=(j.pct||0).toFixed(1)+"%";
            $("#bst-total").textContent=j.total; $("#bst-checked").textContent=j.checked;
            $("#bst-banned").textContent=j.banned; $("#bst-clean").textContent=j.clean;
            $("#bst-unreg").textContent=j.unregistered; $("#bst-inv").textContent=j.invalid;
          } else {
            $("#bulk-bar").style.width=(j.pct||0).toFixed(1)+"%";
            $("#st-total").textContent=j.total; $("#st-checked").textContent=j.checked;
            $("#st-reg").textContent=j.registered; $("#st-unreg").textContent=j.unregistered;
            $("#st-inv").textContent=j.invalid; $("#st-valid").textContent=j.valid;
          }
          if(j.done){
            clearInterval(STATE.pollTimer); STATE.pollTimer=null;
            localStorage.removeItem("active_job");
          }
        }).catch(()=>{});
    }, 1500);
  }catch{}
}

async function loadMyJobs(){
  const list = $("#jobs-list");
  list.innerHTML = "⏳ loading…";
  try{
    const r = await fetch("/api/jobs/mine");
    const d = await r.json();
    if(!d.ok){ list.innerHTML = "error"; return; }
    if(!d.jobs.length){ list.innerHTML = "<div class='muted'>No jobs yet.</div>"; return; }
    list.innerHTML = d.jobs.map(j=>`
      <div class="job-row">
        <div>
          <div><b>${esc(j.kind)}</b> <span class="jid">#${esc(j.id)}</span></div>
          <div class="jmeta">
            <span>Total: ${j.total}</span>
            <span>Checked: ${j.checked}</span>
            <span>Valid: ${j.valid}</span>
            <span>${j.done?"✅ done":"⏳ running"}</span>
          </div>
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn ghost small" onclick="resumeJob('${esc(j.id)}','${esc(j.kind)}')">
            ${j.done?"Open":"Resume"}
          </button>
          <button class="btn small" onclick="downloadJob('${esc(j.id)}')">⬇</button>
        </div>
      </div>
    `).join("");
  }catch(e){ list.innerHTML = "error: "+esc(e.message); }
}
window.loadMyJobs = loadMyJobs;
window.resumeJob = (jid, kind)=>{
  STATE.activeJob = jid;
  localStorage.setItem("active_job", JSON.stringify({job_id: jid, kind}));
  tryResume(localStorage.getItem("active_job"));
};
window.downloadJob = (jid)=>{ window.location = "/api/bulk/download/"+jid; };
$("#jobs-refresh").addEventListener("click", loadMyJobs);

// ═════════════ ADMIN ═════════════
async function loadAdminStats(){
  try{
    const r = await fetch("/api/admin/stats");
    const d = await r.json();
    if(!d.ok) return;
    $("#as-users").textContent = fmt(d.stats.users);
    $("#as-jobs").textContent = fmt(d.stats.jobs_total);
    $("#as-running").textContent = fmt(d.stats.jobs_running);
    $("#as-cadd").textContent = fmt(d.stats.credits_added);
    $("#as-cused").textContent = fmt(d.stats.credits_used);
  }catch{}
}

async function loadAdminUsers(q=""){
  const tbody = $("#admin-users-body");
  tbody.innerHTML = "<tr><td colspan='6'>loading…</td></tr>";
  try{
    const r = await fetch("/api/admin/users"+(q?"?q="+encodeURIComponent(q):""));
    const d = await r.json();
    if(!d.ok){ tbody.innerHTML = "<tr><td colspan='6'>error</td></tr>"; return; }
    if(!d.users.length){ tbody.innerHTML = "<tr><td colspan='6'>no users</td></tr>"; return; }
    tbody.innerHTML = d.users.map(u=>`
      <tr>
        <td>${u.id}</td>
        <td>${esc(u.username)}</td>
        <td>${fmt(u.credits)}</td>
        <td>${u.is_admin?'<span class="badge admin">ADMIN</span>':'-'}</td>
        <td>${u.is_banned?'<span class="badge banned">BANNED</span>':'-'}</td>
        <td class="actions">
          <button class="btn small" onclick="adminAddCredits(${u.id})">+ Credits</button>
          <button class="btn small" onclick="adminToggleBan(${u.id},${u.is_banned})">${u.is_banned?'Unban':'Ban'}</button>
          <button class="btn small" onclick="adminResetPw(${u.id})">Reset PW</button>
          <button class="btn small" onclick="adminToggleAdmin(${u.id},${u.is_admin})">${u.is_admin?'Demote':'Promote'}</button>
        </td>
      </tr>
    `).join("");
  }catch(e){ tbody.innerHTML = "<tr><td colspan='6'>error: "+esc(e.message)+"</td></tr>"; }
}
window.loadAdminUsers = loadAdminUsers;

window.adminAddCredits = async (uid)=>{
  const amt = prompt("Credits to add:");
  if(!amt) return;
  const n = parseInt(amt,10);
  if(!n) return;
  await fetch("/api/admin/user/"+uid,{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({action:"add_credits", amount: n})
  });
  loadAdminUsers($("#admin-search").value);
};
window.adminToggleBan = async (uid, isBanned)=>{
  await fetch("/api/admin/user/"+uid,{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({action: isBanned?"unban":"ban"})
  });
  loadAdminUsers($("#admin-search").value);
};
window.adminToggleAdmin = async (uid, isAdmin)=>{
  await fetch("/api/admin/user/"+uid,{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({action: isAdmin?"remove_admin":"make_admin"})
  });
  loadAdminUsers($("#admin-search").value);
};
window.adminResetPw = async (uid)=>{
  const pw = prompt("New password (min 6):");
  if(!pw || pw.length<6) return;
  await fetch("/api/admin/user/"+uid,{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({action:"reset_password", password: pw})
  });
  alert("Password reset.");
};
$("#admin-search-btn").addEventListener("click", ()=> loadAdminUsers($("#admin-search").value));
$("#admin-reload").addEventListener("click", ()=>{ loadAdminStats(); loadAdminUsers($("#admin-search").value); });

// ═════════════ BOOT ═════════════
(async ()=>{
  try{
    const r = await fetch("/api/auth/me");
    const d = await r.json();
    if(d.ok && d.user){ STATE.user = d.user; enterApp(); }
    else { showView("auth"); loadCaptcha(); }
  }catch{ showView("auth"); loadCaptcha(); }
})();
