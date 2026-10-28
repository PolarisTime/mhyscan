/**
 * mhyscan 遥测接收 Worker (Cloudflare 免费套餐)
 *
 * 客户端上传: Content-Type: application/octet-stream
 *   body = nonce(12B) || AES-256-GCM( gzip( JSON event ) )
 *   header X-Ts   = unix 秒
 *   header X-Sign = hex( HMAC-SHA256( X-Ts || body, TELEMETRY_AUTH ) )
 *
 * 路由:
 *   POST /v1/events 接收事件
 *   GET  /health    健康检查
 *   GET  /stats     聚合概览
 *   scheduled      每日聚合 + 清理过期数据
 */

interface Env {
  DB: D1Database;
  TELEMETRY_AUTH: string;
  TELEMETRY_KEY: string;
  RETENTION_DAYS: string;
  CLOCK_SKEW: string;
  /// 可选：设置后 /stats 需要 ?token= 或 Authorization: Bearer
  STATS_TOKEN?: string;
  /// 部署版本与提交（wrangler vars / --var 注入）
  SERVICE_VERSION?: string;
  GIT_SHA?: string;
  /// 会话 token 签名密钥（缺省回退 TELEMETRY_AUTH）
  SESSION_KEY?: string;
  /// token 有效期（秒，默认 1800）
  TOKEN_TTL?: string;
  /// 每 install_id 每分钟事件配额（默认 600）
  RATE_LIMIT_PER_MIN?: string;
  /// 每 install_id 每分钟会话配额（默认 10）
  RATE_LIMIT_SESSIONS_PER_MIN?: string;
}

interface TelemetryEvent {
  event_id?: string;
  schema_version?: number;
  install_id: string;
  session_id?: string;
  event: string;
  ts?: number;
  app_version?: string;
  props?: Record<string, unknown>;
}

const API_VERSION = "v1";
const BASE = `/${API_VERSION}`;

/** RFC 9457 Problem Details */
function problem(
  status: number,
  title: string,
  detail?: string,
  instance?: string,
  headers: Record<string, string> = {},
): Response {
  const body = {
    type: "about:blank",
    title,
    status,
    ...(detail ? { detail } : {}),
    ...(instance ? { instance } : {}),
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/problem+json",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

function allowHeader(allow: string[]): Record<string, string> {
  return { allow: [...allow, "OPTIONS"].join(", ") };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const method = request.method.toUpperCase();

    // 资源 → 允许的方法（仅 /v1，无兼容别名）
    const routes: Record<string, string[]> = {
      [`${BASE}/sessions`]: ["POST"],
      [`${BASE}/events`]: ["POST"],
      [`${BASE}/health`]: ["GET", "HEAD"],
      [`${BASE}/stats`]: ["GET", "HEAD"],
    };

    if (path === "/" && method === "GET") return index();

    const allow = routes[path];
    if (!allow) return problem(404, "Not Found", `${method} ${path} 未找到`, path);
    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: allowHeader(allow) });
    }
    if (!allow.includes(method)) {
      return problem(405, "Method Not Allowed", undefined, path, allowHeader(allow));
    }

    if (path === `${BASE}/health`) return health(request, env);
    if (path === `${BASE}/sessions`) return createSession(request, env);
    if (path === `${BASE}/events`) {
      const ct = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
      if (ct !== "application/octet-stream") {
        return problem(415, "Unsupported Media Type", "Content-Type 必须为 application/octet-stream", path);
      }
      return collect(request, env);
    }

    const denied = statsAuth(request, env);
    if (denied) return denied;
    return stats(request, env, url);
  },

  async scheduled(_event: ScheduledController, env: Env): Promise<void> {
    const retention = parseInt(env.RETENTION_DAYS || "90", 10);

    // 聚合最近 2 天（含今天，便于修正）
    await env.DB.prepare(
      `INSERT OR REPLACE INTO daily_stats (day, event, installs, total)
       SELECT date(ts, 'unixepoch') AS day,
              event,
              COUNT(DISTINCT install_id) AS installs,
              COUNT(*) AS total
       FROM events
       WHERE ts >= unixepoch('now', '-2 day')
       GROUP BY day, event`
    ).run();

    // 清理过期原始事件
    await env.DB.prepare(`DELETE FROM events WHERE ts < unixepoch('now', ?)`)
      .bind(`-${retention} day`)
      .run();

    // 清理过期的限流计数（只保留最近 1 小时）
    await env.DB.prepare(
      `DELETE FROM rate_limits WHERE window_start < unixepoch('now', '-1 hour')`,
    ).run();
  },
} satisfies ExportedHandler<Env>;

function index(): Response {
  return new Response(
    JSON.stringify({
      service: "mhyscan-telemetry",
      version: API_VERSION,
      endpoints: {
        sessions: { method: "POST", path: `${BASE}/sessions`, media_type: "application/json" },
        events: { method: "POST", path: `${BASE}/events`, media_type: "application/octet-stream" },
        health: { method: "GET", path: `${BASE}/health` },
        stats: { method: "GET", path: `${BASE}/stats`, query: { days: "1..365, default 60" } },
      },
    }),
    { status: 200, headers: { "content-type": "application/json", "cache-control": "no-store" } },
  );
}

function statsAuth(request: Request, env: Env): Response | null {
  if (!env.STATS_TOKEN) return null;
  const bearer = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  const token = new URL(request.url).searchParams.get("token") || bearer || "";
  if (token !== env.STATS_TOKEN) {
    return problem(401, "Unauthorized", "缺少或错误的 STATS_TOKEN", "/v1/stats", {
      "www-authenticate": 'Bearer realm="stats"',
    });
  }
  return null;
}

function sessionKey(env: Env): string {
  return env.SESSION_KEY || env.TELEMETRY_AUTH || "";
}

async function hmacHex(key: string, data: Uint8Array): Promise<string> {
  const k = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", k, data);
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function issueSession(installId: string, env: Env): Promise<{ token: string; expires_in: number }> {
  const now = Math.floor(Date.now() / 1000);
  const ttl = parseInt(env.TOKEN_TTL || "1800", 10);
  const payload = b64url(
    new TextEncoder().encode(JSON.stringify({ sub: installId, iat: now, exp: now + ttl })),
  );
  const sig = await hmacHex(sessionKey(env), new TextEncoder().encode(payload));
  return { token: `${payload}.${sig}`, expires_in: ttl };
}

async function verifySession(token: string, env: Env): Promise<{ sub: string } | null> {
  const parts = token.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  const [payload, sig] = parts;
  const expected = await hmacHex(sessionKey(env), new TextEncoder().encode(payload));
  if (expected !== sig.toLowerCase()) return null;
  try {
    const data = JSON.parse(new TextDecoder().decode(b64urlDecode(payload))) as {
      sub?: string;
      iat?: number;
      exp?: number;
    };
    const now = Math.floor(Date.now() / 1000);
    if (typeof data.sub !== "string" || !data.sub) return null;
    if (typeof data.exp !== "number" || data.exp < now) return null;
    if (typeof data.iat !== "number" || data.iat > now + 300) return null;
    return { sub: data.sub };
  } catch {
    return null;
  }
}

async function bumpRate(
  env: Env,
  bucket: string,
  cost: number,
  limit: number,
): Promise<{ allowed: boolean; retryAfter: number }> {
  const now = Math.floor(Date.now() / 1000);
  const windowStart = now - (now % 60);
  await env.DB.prepare(
    `INSERT INTO rate_limits (bucket, window_start, count) VALUES (?, ?, ?)
       ON CONFLICT(bucket, window_start) DO UPDATE SET count = count + excluded.count`,
  )
    .bind(bucket, windowStart, cost)
    .run();
  const row = await env.DB.prepare(
    `SELECT count FROM rate_limits WHERE bucket = ? AND window_start = ?`,
  )
    .bind(bucket, windowStart)
    .first<{ count: number }>();
  const count = Number(row?.count ?? cost);
  return { allowed: count <= limit, retryAfter: 60 - (now % 60) };
}

async function createSession(request: Request, env: Env): Promise<Response> {
  const auth = await readSignedBody(request, env);
  if ("error" in auth) return auth.error;

  let installId = "";
  try {
    const body = JSON.parse(new TextDecoder().decode(auth.body)) as { install_id?: string };
    installId = String(body.install_id || "");
  } catch {
    return problem(400, "Bad Request", "body 必须是 JSON {install_id}");
  }
  if (!/^[0-9a-f]{32}$/i.test(installId)) {
    return problem(422, "Unprocessable Content", "install_id 必须是 32 位 hex", "/v1/sessions");
  }

  const limit = parseInt(env.RATE_LIMIT_SESSIONS_PER_MIN || "10", 10);
  const rate = await bumpRate(env, `sessions:${installId}`, 1, limit);
  if (!rate.allowed) {
    return problem(429, "Too Many Requests", `会话请求超过 ${limit} 次/分钟`, "/v1/sessions", {
      "retry-after": String(rate.retryAfter),
    });
  }

  const session = await issueSession(installId, env);
  return new Response(JSON.stringify({ token_type: "Bearer", ...session }), {
    status: 201,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

async function readSignedBody(
  request: Request,
  env: Env,
): Promise<{ body: Uint8Array } | { error: Response }> {
  const tsHeader = request.headers.get("X-Ts");
  const signHeader = request.headers.get("X-Sign");
  if (!tsHeader || !signHeader) {
    return { error: problem(401, "Unauthorized", "缺少 X-Ts / X-Sign") };
  }
  const ts = parseInt(tsHeader, 10);
  const skew = parseInt(env.CLOCK_SKEW || "300", 10);
  const now = Math.floor(Date.now() / 1000);
  if (!Number.isFinite(ts) || Math.abs(now - ts) > skew) {
    return { error: problem(401, "Unauthorized", "时间戳超出允许的时钟偏移") };
  }
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length === 0 || body.length > 64 * 1024) {
    return { error: problem(413, "Payload Too Large", "body 必须为 1B..64KB") };
  }
  if (!(await verifyHmac(tsHeader, body, signHeader, env.TELEMETRY_AUTH))) {
    return { error: problem(401, "Unauthorized", "HMAC 验签失败") };
  }
  return { body };
}

async function health(request: Request, env: Env): Promise<Response> {
  const started = Date.now();
  let dbOk = false;
  let dbError: string | undefined;
  try {
    await env.DB.prepare("SELECT 1 AS ok").first();
    dbOk = true;
  } catch (e) {
    dbError = e instanceof Error ? e.message.slice(0, 120) : "unavailable";
  }
  const latency = Date.now() - started;
  const body = {
    status: dbOk ? "ok" : "degraded",
    service: "mhyscan-telemetry",
    version: env.SERVICE_VERSION || "dev",
    commit: env.GIT_SHA || null,
    time: Math.floor(Date.now() / 1000),
    checks: {
      db: { ok: dbOk, latency_ms: latency, ...(dbError ? { error: dbError } : {}) },
    },
    runtime: { colo: (request.cf?.colo as string | undefined) ?? null },
  };
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "cache-control": "no-store",
  };
  const status = dbOk ? 200 : 503;
  return new Response(request.method === "HEAD" ? null : JSON.stringify(body), { status, headers });
}

async function collect(request: Request, env: Env): Promise<Response> {
  // 1) 请求签名（时钟窗口 + HMAC）
  const auth = await readSignedBody(request, env);
  if ("error" in auth) return auth.error;
  const body = auth.body;

  // 2) 会话 token（客户端启动时换取，短有效期）
  const bearer = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") || "";
  if (!bearer) {
    return problem(401, "Unauthorized", "缺少 Bearer token", "/v1/events", {
      "www-authenticate": 'Bearer realm="events"',
    });
  }
  const session = await verifySession(bearer, env);
  if (!session) {
    return problem(401, "Unauthorized", "会话 token 无效或已过期", "/v1/events", {
      "www-authenticate": 'Bearer realm="events"',
    });
  }

  // 2) AES-256-GCM 解密
  let plain: Uint8Array;
  try {
    plain = await decrypt(body, env.TELEMETRY_KEY);
  } catch {
    return problem(400, "Bad Request", "AES-256-GCM 解密失败");
  }

  // 3) gzip 解压
  let text: string;
  try {
    text = await gunzip(plain);
  } catch {
    return problem(400, "Bad Request", "gzip 解压失败");
  }

  // 4) 解析（兼容单条对象或数组批量）并入库
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return problem(400, "Bad Request", "JSON 解析失败");
  }
  const list: unknown[] = Array.isArray(data) ? data : [data];
  if (list.length === 0 || list.length > 256) {
    return problem(422, "Unprocessable Content", "批量条数必须为 1..256");
  }

  // token 必须与事件 install_id 一致（防止拿 A 的 token 上报 B 的数据）
  const mismatched = list.some((raw) => {
    const ev = raw as TelemetryEvent | null;
    return !!ev && typeof ev.install_id === "string" && ev.install_id !== session.sub;
  });
  if (mismatched) return problem(403, "Forbidden", "token 与 install_id 不匹配");

  // 按 install_id 的每分钟配额
  const limit = parseInt(env.RATE_LIMIT_PER_MIN || "600", 10);
  const rate = await bumpRate(env, `events:${session.sub}`, list.length, limit);
  if (!rate.allowed) {
    return problem(429, "Too Many Requests", `事件上报超过 ${limit} 条/分钟`, "/v1/events", {
      "retry-after": String(rate.retryAfter),
    });
  }

  const now = Math.floor(Date.now() / 1000);
  const ipPrefix = truncateIp(request.headers.get("CF-Connecting-IP") || "");

  let accepted = 0;
  // 分批写入，避免单次 batch 语句过多
  for (let i = 0; i < list.length; i += 64) {
    const stmts: D1PreparedStatement[] = [];
    for (const raw of list.slice(i, i + 64)) {
      const ev = raw as TelemetryEvent;
      if (!ev || !ev.install_id || !ev.event) continue;
      accepted += 1;
      const eventTs = Number.isFinite(Number(ev.ts)) ? Number(ev.ts) : now;

      stmts.push(
        env.DB.prepare(
          `INSERT OR IGNORE INTO events
             (event_id, schema_version, ts, install_id, session_id, event, app_version, props, ip_prefix)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
        ).bind(
          str(ev.event_id),
          num(ev.schema_version),
          eventTs,
          ev.install_id,
          ev.session_id ?? null,
          ev.event,
          ev.app_version ?? null,
          JSON.stringify(ev.props ?? {}),
          ipPrefix
        )
      );

      // 只有 scan_success 才进成功表；scan_result 是失败/尝试，仅留在 events
      if (ev.event === "scan_success") {
        const p = (ev.props ?? {}) as Record<string, unknown>;
        stmts.push(
          env.DB.prepare(
            `INSERT OR IGNORE INTO scan_success
               (event_id, ts, install_id, platform, rid, uid_hash, latency_ms, attempts, ip_prefix)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
          ).bind(
            str(ev.event_id),
            eventTs,
            ev.install_id,
            str(p.platform),
            str(p.rid),
            str(p.uid_hash),
            num(p.detect_latency_ms),
            num(p.attempt_count),
            ipPrefix
          )
        );
      }
    }
    if (stmts.length) await env.DB.batch(stmts);
  }

  return new Response(
    JSON.stringify({ accepted: list.length, rejected: list.length - accepted }),
    { status: 202, headers: { "content-type": "application/json", "cache-control": "no-store" } },
  );
}

async function stats(request: Request, env: Env, url: URL): Promise<Response> {
  const raw = url.searchParams.get("days") ?? "60";
  const days = Number(raw);
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    return problem(400, "Bad Request", "days 必须是 1..365 的整数", url.pathname);
  }
  const since = `-${days} day`;
  const windowStart = `unixepoch('now', ?)`;

  // 直接聚合 events（daily_stats 只由 Cron 每天写一次，不能反映实时状态）
  const totals = await env.DB.prepare(
    `SELECT COUNT(*) AS events,
            COUNT(DISTINCT install_id) AS installs,
            COALESCE(MAX(ts), 0) AS latest_ts
       FROM events
      WHERE ts >= ${windowStart}`
  )
    .bind(since)
    .first<{ events: number; installs: number; latest_ts: number }>();

  const byEvent = await env.DB.prepare(
    `SELECT event, COUNT(*) AS total, COUNT(DISTINCT install_id) AS installs
       FROM events
      WHERE ts >= ${windowStart}
      GROUP BY event
      ORDER BY total DESC
      LIMIT 50`
  )
    .bind(since)
    .all();

  const byDay = await env.DB.prepare(
    `SELECT date(ts, 'unixepoch') AS day,
            event,
            COUNT(*) AS total,
            COUNT(DISTINCT install_id) AS installs
       FROM events
      WHERE ts >= ${windowStart}
      GROUP BY day, event
      ORDER BY day DESC, total DESC
      LIMIT 200`
  )
    .bind(since)
    .all();

  const success = await env.DB.prepare(
    `SELECT platform, COUNT(*) AS total, COUNT(DISTINCT install_id) AS installs
       FROM scan_success
      WHERE ts >= ${windowStart}
      GROUP BY platform
      ORDER BY total DESC`
  )
    .bind(since)
    .all();

  const rate = await env.DB.prepare(`SELECT COUNT(*) AS buckets FROM rate_limits`)
    .first<{ buckets: number }>();

  const body = {
    generated_at: Math.floor(Date.now() / 1000),
    window_days: days,
    totals: {
      events: totals?.events ?? 0,
      installs: totals?.installs ?? 0,
      latest_event_at: totals?.latest_ts || null,
    },
    by_event: byEvent.results ?? [],
    by_day: byDay.results ?? [],
    success: success.results ?? [],
    rate_limit_buckets: rate?.buckets ?? 0,
  };
  return new Response(request.method === "HEAD" ? null : JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/* ---------------- crypto helpers ---------------- */

async function verifyHmac(ts: string, body: Uint8Array, sigHex: string, auth: string): Promise<boolean> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(auth),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"]
  );
  const data = concat(new TextEncoder().encode(ts), body);
  const sig = hexToBytes(sigHex);
  if (!sig) return false;
  return crypto.subtle.verify("HMAC", key, sig, data);
}

async function decrypt(framed: Uint8Array, keyHex: string): Promise<Uint8Array> {
  const keyBytes = hexToBytes(keyHex);
  if (!keyBytes || keyBytes.length !== 32) throw new Error("bad key");
  const key = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["decrypt"]);
  const iv = framed.slice(0, 12);
  const ct = framed.slice(12);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ct);
  return new Uint8Array(plain);
}

async function gunzip(data: Uint8Array): Promise<string> {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

/* ---------------- utils ---------------- */

function hexToBytes(hex: string): Uint8Array | null {
  if (!/^[0-9a-fA-F]*$/.test(hex) || hex.length % 2 !== 0) return null;
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/** IP 隐私化: IPv4 抹去末段, IPv6 保留 /48 前缀 */
function truncateIp(ip: string): string {
  if (!ip) return "";
  if (ip.includes(".")) {
    const p = ip.split(".");
    return p.length === 4 ? `${p[0]}.${p[1]}.${p[2]}.0` : ip;
  }
  const p = ip.split(":");
  return p.slice(0, 3).join(":");
}

function str(v: unknown): string | null {
  return typeof v === "string" ? v : v == null ? null : String(v);
}
function num(v: unknown): number | null {
  return typeof v === "number" ? v : v == null ? null : Number(v) || null;
}
function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
