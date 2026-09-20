/* mhyscan UI — 同时支持 Tauri 后端与浏览器 demo(mock) */

const $ = (id) => document.getElementById(id);
const IN_TAURI = typeof window.__TAURI__ !== "undefined";
const TAURI = IN_TAURI ? window.__TAURI__ : null;

const DEMO_ACCOUNTS = [
  { name: "账号244202754", uid: "244202754", type: "官服" },
];
const DEMO_LOGS = [
  "mhyscan 就绪 (openh264 + rxing)",
  "获取直播流地址成功: B站 直播间 6",
  "直播流已连接 (HTTP-FLV 低延迟)",
  "二维码识别引擎 rxing 就绪",
  "等待识别米哈游登录二维码...",
];

let accounts = [];
let currentUid = null;
let records = [];
let scanning = false;
let tab = "ALL";
const t0 = Date.now();

/* ---------- 日志 ---------- */
const stamp = () => new Date().toTimeString().slice(0, 8);
const catOf = (t) => (["STREAM", "QR", "LOGIN"].includes(t) ? t : "OTHER");
function classify(line) {
  if (/错误|失败|Error/.test(line)) return "ERROR";
  if (/抢码|登录|scanQRLogin|confirm/.test(line)) return "LOGIN";
  if (/二维码|识别|rxing/.test(line)) return "QR";
  if (/直播流|拉流|FLV|流地址|B站|抖音|预热/.test(line)) return "STREAM";
  return "SYSTEM";
}
function log(text) {
  updateProgress(text);
  if (isProgress(text)) return; // 进度只更新指标，不刷日志
  const t = classify(text);
  const el = document.createElement("div");
  el.className = "ln " + (["STREAM", "QR", "LOGIN", "ERROR"].includes(t) ? t : "");
  el.dataset.cat = catOf(t);
  el.innerHTML = `<span class="ts">${stamp()}</span><span class="tag">${t}</span><span class="msg"></span>`;
  el.querySelector(".msg").textContent = text;
  $("log").appendChild(el);
  applyFilter(el);
  $("log").scrollTop = $("log").scrollHeight;
}
const applyFilter = (el) => el.classList.toggle("hide", tab !== "ALL" && el.dataset.cat !== tab);

const PROGRESS_RE = /等待 (\d+)s · 流量 ([\d.]+)MB · 帧 (\d+) · 识别 (\d+) · 内存 (\d+)MB/;
function isProgress(text) {
  return PROGRESS_RE.test(text) || text.startsWith("PROGRESS ");
}
function updateProgress(text) {
  const m = text.match(PROGRESS_RE);
  if (!m) return;
  const secs = parseInt(m[1], 10);
  $("mTime").textContent = new Date(secs * 1000).toISOString().slice(11, 19);
  $("mFrames").textContent = m[3];
  $("mQr").textContent = m[4];
}

/* ---------- 二维码弹窗 ---------- */
function showModal(title, status) {
  $("modalTitle").textContent = title;
  $("modalStatus").textContent = status || "正在生成二维码…";
  $("qrImg").removeAttribute("src");
  $("qrText").textContent = "";
  $("modal").classList.add("show");
}
function hideModal() {
  $("modal").classList.remove("show");
}

/* ---------- 账号（单账号） ---------- */
function renderAccounts() {
  if (!accounts.length) {
    $("accounts").innerHTML = '<p style="color:var(--dim);font-size:12px;padding:6px">暂无账号，点右上「扫码登录」</p>';
    $("ready").textContent = "—";
    return;
  }
  if (!currentUid || !accounts.some((a) => a.uid === currentUid)) currentUid = accounts[0].uid;
  $("accounts").innerHTML = accounts
    .map(
      (a) => `<div class="acct ${a.uid === currentUid ? "on" : ""}" data-uid="${a.uid}">
      <span class="cb"></span>
      <span class="name">${a.name}<span class="uid">UID ${a.uid}</span></span>
      <span class="type">${a.type || ""}</span></div>`
    )
    .join("");
  $("accounts").querySelectorAll(".acct").forEach((el) =>
    el.addEventListener("click", () => {
      currentUid = el.dataset.uid;
      renderAccounts();
    })
  );
  const cur = accounts.find((a) => a.uid === currentUid);
  $("ready").textContent = cur ? cur.name : "—";
}
async function refreshAccounts() {
  try {
    accounts = IN_TAURI ? await TAURI.core.invoke("list_accounts") : DEMO_ACCOUNTS;
  } catch (e) {
    accounts = [];
    log("账号读取失败: " + e);
  }
  renderAccounts();
}

/* ---------- 记录 ---------- */
function renderRecords() {
  $("recCount").textContent = records.length + " 条";
  $("records").innerHTML = records.length
    ? records
        .map(
          (r) => `<div class="rec">
        <div><div class="code"><span class="tick"></span>${r.ticket}</div><div class="meta">${r.desc}</div></div>
        <div class="who">${r.who}</div><div class="time">${r.time}</div></div>`
        )
        .join("")
    : '<div class="empty">暂无记录，等待直播间出现登录二维码…</div>';
}
function addRecordFromLog(text) {
  const m = text.match(/(?:tk=|ticket=|ticket=)([0-9a-fA-F-]{8,})/);
  if (!m) return;
  const ticket = m[1];
  if (records.some((r) => r.ticket === ticket)) return;
  records.unshift({
    ticket: ticket.slice(0, 20),
    desc: `${$("platform").value === "douyin" ? "抖音" : "B站"} · 直播间 ${$("rid").value}`,
    who: accounts.find((a) => a.uid === currentUid)?.name || "—",
    time: stamp(),
  });
  renderRecords();
}

/* ---------- 状态 ---------- */
function setStatus(text, kind) {
  $("status").textContent = text;
  $("dot").className = "dot " + (kind || "");
}
function setScanUI(on) {
  scanning = on;
  $("start").textContent = on ? "停止扫描" : "启动扫描";
  $("start").classList.toggle("stop", on);
  $("monitor").classList.toggle("live", on);
  setStatus(on ? "扫描中" : "就绪", on ? "busy" : "ok");
  $("streamDot").className = "dot " + (on ? "ok" : "");
  $("mStream").textContent = on ? "已连接" : "未连接";
  $("mStream").classList.toggle("live", on);
  $("mTitle").textContent = on ? "正在监听直播流，识别登录二维码…" : "未启动识别监视";
  $("mHint").textContent = on
    ? `RID ${$("rid").value} · ${$("quality").value}`
    : "点击左侧「启动扫描」开始监听直播流";
}

/* ---------- 启停 ---------- */
async function toggle() {
  if (!IN_TAURI) {
    setScanUI(!scanning);
    log(scanning ? `启动扫描 · ${$("platform").value} · RID ${$("rid").value}` : "已停止扫描");
    return;
  }
  if (scanning) {
    await TAURI.core.invoke("stop_scan");
    return;
  }
  const platform = $("platform").value;
  const rid = $("rid").value.trim();
  if (!rid) {
    log("请先填写房间号 RID");
    return;
  }
  setScanUI(true);
  log(`启动扫描 · ${platform} · RID ${rid}`);
  try {
    await TAURI.core.invoke("scan", { platform, rid, timeout: 86400 });
  } catch (e) {
    log("错误: " + e);
    setScanUI(false);
  }
}

/* ---------- 事件 ---------- */
$("start").addEventListener("click", toggle);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target === document.body) {
    e.preventDefault();
    toggle();
  }
});
$("tabs").addEventListener("click", (e) => {
  const t = e.target.closest(".tab");
  if (!t) return;
  tab = t.dataset.tab;
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === t));
  document.querySelectorAll(".ln").forEach(applyFilter);
});
$("interval").addEventListener("input", (e) => ($("iv").textContent = e.target.value));
$("tel").addEventListener("click", (e) => e.target.classList.toggle("on"));
$("clear").addEventListener("click", () => ($("log").innerHTML = ""));
$("platform").addEventListener("change", (e) => ($("platChip").textContent = e.target.value === "douyin" ? "抖音" : "B站"));
$("login").addEventListener("click", async () => {
  if (!IN_TAURI) {
    log("米游社扫码登录（demo）");
    return;
  }
  showModal("米游社扫码登录", "正在生成二维码…");
  try {
    await TAURI.core.invoke("start_login");
  } catch (e) {
    $("modalStatus").textContent = "登录失败: " + e;
  }
});
$("biliLogin").addEventListener("click", async () => {
  if (!IN_TAURI) {
    log("B站扫码登录（demo）");
    return;
  }
  showModal("B站扫码登录", "正在生成二维码…");
  try {
    await TAURI.core.invoke("start_bili_login");
  } catch (e) {
    $("modalStatus").textContent = "登录失败: " + e;
  }
});
$("modalClose").addEventListener("click", hideModal);
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) hideModal();
});

/* ---------- 初始化 ---------- */
(async () => {
  if (IN_TAURI) {
    await TAURI.event.listen("scan-log", (e) => {
      log(e.payload);
      addRecordFromLog(e.payload);
    });
    await TAURI.event.listen("scan-done", (e) => {
      log("== " + e.payload + " ==");
      setScanUI(false);
    });
    await TAURI.event.listen("login-qr", (e) => {
      $("qrImg").src = e.payload;
      $("modalStatus").textContent = "请用对应 App 扫码";
    });
    await TAURI.event.listen("login-qr-text", (e) => {
      $("qrText").textContent = e.payload;
    });
    await TAURI.event.listen("login-status", (e) => {
      $("modalStatus").textContent = "状态: " + e.payload;
      log("登录状态: " + e.payload);
    });
    await TAURI.event.listen("login-done", (e) => {
      $("modalStatus").textContent = "登录成功: " + e.payload;
      log("登录成功: " + e.payload);
      refreshAccounts();
      setTimeout(hideModal, 1200);
    });
    await refreshAccounts();
  } else {
    renderAccounts();
    DEMO_LOGS.forEach(log);
  }
  renderRecords();
  setInterval(() => ($("latency").textContent = String(18 + Math.floor(Math.random() * 14))), 1500);
})();
