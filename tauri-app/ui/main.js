/* mhyscan UI — 演示（mock，未接后端） */

const $ = (id) => document.getElementById(id);

const ACCOUNTS = [
  { name: "账号244202754", uid: "244202754", type: "官服" },
  { name: "账号100863920", uid: "100863920", type: "官服" },
  { name: "账号18029381", uid: "18029381", type: "B服" },
];
const SEED_RECORD = { ticket: "c1fd9c8b-840c", desc: "B站 · 直播间 6", who: "账号244202754", time: "19:30:45" };
const SEED_LOGS = [
  "mhyscan v0.1.0 就绪 (openh264 + rxing)",
  "获取直播流地址成功: B站 直播间 6",
  "直播流已连接 (HTTP-FLV 低延迟)",
  "识别引擎 rxing 就绪, 约 6ms/帧",
  "等待识别米哈游登录二维码...",
  "账号244202754: scanQRLogin 成功",
  "账号244202754: confirmQRLogin 成功",
];

let currentUid = ACCOUNTS[0].uid;
let records = [];
let scanning = false;
let tab = "ALL";

/* ---------- 日志 ---------- */
const stamp = () => new Date().toTimeString().slice(0, 8);
const cat = (t) => (["STREAM", "QR", "LOGIN"].includes(t) ? t : "OTHER");
function tag(line) {
  if (/错误|失败|Error/.test(line)) return "ERROR";
  if (/抢码|登录|账号|scanQRLogin|confirm/.test(line)) return "LOGIN";
  if (/二维码|识别|rxing/.test(line)) return "QR";
  if (/直播流|拉流|FLV|流地址|B站|抖音/.test(line)) return "STREAM";
  return "SYSTEM";
}
function log(text) {
  const t = tag(text);
  const el = document.createElement("div");
  el.className = "ln " + (["STREAM", "QR", "LOGIN", "ERROR"].includes(t) ? t : "");
  el.dataset.cat = cat(t);
  el.innerHTML = `<span class="ts">${stamp()}</span><span class="tag">${t}</span><span class="msg"></span>`;
  el.querySelector(".msg").textContent = text;
  $("log").appendChild(el);
  applyFilter(el);
  $("log").scrollTop = $("log").scrollHeight;
}
const applyFilter = (el) => el.classList.toggle("hide", tab !== "ALL" && el.dataset.cat !== tab);

/* ---------- 账号（单账号） ---------- */
function renderAccounts() {
  $("accounts").innerHTML = ACCOUNTS.map((a) => `
    <div class="acct ${a.uid === currentUid ? "on" : ""}" data-uid="${a.uid}">
      <span class="cb"></span>
      <span class="name">${a.name}<span class="uid">UID ${a.uid}</span></span>
      <span class="type">${a.type}</span>
    </div>`).join("");
  $("accounts").querySelectorAll(".acct").forEach((el) =>
    el.addEventListener("click", () => {
      currentUid = el.dataset.uid;
      renderAccounts();
    })
  );
  const cur = ACCOUNTS.find((a) => a.uid === currentUid);
  $("ready").textContent = cur ? cur.name : "—";
}

/* ---------- 记录 ---------- */
function renderRecords() {
  $("recCount").textContent = records.length + " 条";
  $("mQr").textContent = records.length;
  $("records").innerHTML = records.length
    ? records.map((r) => `<div class="rec">
        <div><div class="code"><span class="tick"></span>${r.ticket}</div><div class="meta">${r.desc}</div></div>
        <div class="who">${r.who}</div>
        <div class="time">${r.time}</div>
      </div>`).join("")
    : '<div class="empty">暂无记录，等待直播间出现登录二维码…</div>';
}

/* ---------- 启停（视觉占位） ---------- */
function setStatus(text, kind) {
  $("status").textContent = text;
  $("dot").className = "dot " + (kind || "");
}
function toggle() {
  scanning = !scanning;
  $("start").textContent = scanning ? "停止扫描" : "启动扫描";
  $("start").classList.toggle("stop", scanning);
  $("monitor").classList.toggle("live", scanning);
  setStatus(scanning ? "扫描中" : "就绪", scanning ? "busy" : "ok");
  $("streamDot").className = "dot " + (scanning ? "ok" : "");
  $("mStream").textContent = scanning ? "已连接" : "未连接";
  $("mStream").classList.toggle("live", scanning);
  $("mTitle").textContent = scanning ? "正在监听直播流，识别登录二维码…" : "未启动识别监视";
  $("mHint").textContent = scanning ? `RID ${$("rid").value} · ${$("quality").value}` : "点击左侧「启动扫描」开始监听直播流";
  log(scanning ? `启动扫描 · ${$("platform").value} · RID ${$("rid").value}` : "已停止扫描");
}

/* ---------- 事件 ---------- */
$("start").addEventListener("click", toggle);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target === document.body) { e.preventDefault(); toggle(); }
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
$("login").addEventListener("click", () => log("扫码登录：请用米游社 App 扫描（演示）"));
$("platform").addEventListener("change", (e) => ($("platChip").textContent = e.target.value === "douyin" ? "抖音" : "B站"));
setInterval(() => ($("latency").textContent = String(18 + Math.floor(Math.random() * 14))), 1500);

/* ---------- 初始化 ---------- */
renderAccounts();
records = [{ ...SEED_RECORD }];
renderRecords();
SEED_LOGS.forEach(log);
