/**
 * mhyscan 遥测接收 Worker (Cloudflare 免费套餐)
 *
 * 客户端上传: Content-Type: application/octet-stream
 *   body = nonce(12B) || AES-256-GCM( gzip( JSON event ) )
 *   header X-Ts   = unix 秒
 *   header X-Sign = hex( HMAC-SHA256( X-Ts || body, TELEMETRY_AUTH ) )
 *
 * 路由:
 *   POST /collect   接收事件
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "mhyscan-telemetry" });
    }
    if (request.method === "GET" && url.pathname === "/stats") {
      return stats(env);
    }
    if (request.method === "POST" && url.pathname === "/collect") {
      return collect(request, env);
    }
    return json({ error: "not found" }, 404);
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
  },
} satisfies ExportedHandler<Env>;

async function collect(request: Request, env: Env): Promise<Response> {
  const tsHeader = request.headers.get("X-Ts");
  const signHeader = request.headers.get("X-Sign");
  if (!tsHeader || !signHeader) return json({ error: "missing signature" }, 401);

  const ts = parseInt(tsHeader, 10);
  const skew = parseInt(env.CLOCK_SKEW || "300", 10);
  const now = Math.floor(Date.now() / 1000);
  if (!Number.isFinite(ts) || Math.abs(now - ts) > skew) {
    return json({ error: "expired" }, 401);
  }

  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length === 0 || body.length > 64 * 1024) {
    return json({ error: "bad size" }, 413);
  }

  // 1) HMAC 验签
  const ok = await verifyHmac(tsHeader, body, signHeader, env.TELEMETRY_AUTH);
  if (!ok) return json({ error: "bad signature" }, 401);

  // 2) AES-256-GCM 解密
  let plain: Uint8Array;
  try {
    plain = await decrypt(body, env.TELEMETRY_KEY);
  } catch {
    return json({ error: "decrypt failed" }, 400);
  }

  // 3) gzip 解压
  let text: string;
  try {
    text = await gunzip(plain);
  } catch {
    return json({ error: "decompress failed" }, 400);
  }

  // 4) 解析（兼容单条对象或数组批量）并入库
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const list: unknown[] = Array.isArray(data) ? data : [data];
  if (list.length === 0 || list.length > 256) {
    return json({ error: "bad batch size" }, 400);
  }

  const ipPrefix = truncateIp(request.headers.get("CF-Connecting-IP") || "");

  // 分批写入，避免单次 batch 语句过多
  for (let i = 0; i < list.length; i += 64) {
    const stmts: D1PreparedStatement[] = [];
    for (const raw of list.slice(i, i + 64)) {
      const ev = raw as TelemetryEvent;
      if (!ev || !ev.install_id || !ev.event) continue;
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

      if (ev.event === "scan_success" || ev.event === "scan_result") {
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

  return json({ ok: true, count: list.length });
}

async function stats(env: Env): Promise<Response> {
  const daily = await env.DB.prepare(
    `SELECT day, event, installs, total FROM daily_stats ORDER BY day DESC LIMIT 60`
  ).all();
  const success = await env.DB.prepare(
    `SELECT platform, COUNT(*) AS total, COUNT(DISTINCT uid_hash) AS uniq
     FROM scan_success WHERE uid_hash IS NOT NULL GROUP BY platform`
  ).all();
  return json({ daily: daily.results, success: success.results });
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
    headers: { "content-type": "application/json" },
  });
}
