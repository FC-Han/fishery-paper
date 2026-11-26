/**
 * POST /api/embed —— 语义检索的 embedding 代理
 *
 * 站是纯静态的（GitHub Pages），embedding 的 key 绝不能出现在前端，
 * 所以用这一个函数把「文本 → 向量」包起来，浏览器只认这个地址。
 *
 * 请求：POST { "text": "大黄鱼 养殖" }
 * 响应：{ "v": [0.013, -0.24, ...], "dim": 1024, "model": "BAAI/bge-m3", "cached": false }
 *
 * 环境变量（Vercel → Settings → Environment Variables）：
 *   EMBED_API_KEY   必填，服务商密钥
 *   EMBED_API_BASE  默认 https://api.siliconflow.cn/v1/embeddings
 *   EMBED_MODEL     默认 BAAI/bge-m3（1024 维，中英混排可用，免费额度够）
 *   ALLOW_ORIGINS   允许的前端来源，逗号分隔
 *   DAILY_BUDGET    单实例每天最多放行多少次（软限额，防刷）
 */

const DEFAULTS = {
  base: "https://api.siliconflow.cn/v1/embeddings",
  model: "BAAI/bge-m3",
  allowOrigins: "https://fc-han.github.io,http://localhost:8000,http://127.0.0.1:8000",
  dailyBudget: 3000,
};

const MAX_CHARS = 400;        // 查询串不会长，超了直接拒
const MAX_BODY = 4096;
const UPSTREAM_TIMEOUT = 8000;
const CACHE_MAX = 500;

// 单实例内的缓存与限流。Serverless 实例会被回收，所以这只是"尽力而为"，
// 真正防刷靠 DAILY_BUDGET + 服务商侧配额。
const cache = new Map();
const hits = new Map();
let day = "";
let dayCount = 0;

function today() {
  return new Date().toISOString().slice(0, 10);
}

function clientIp(req) {
  const fwd = req.headers["x-forwarded-for"];
  if (typeof fwd === "string" && fwd) return fwd.split(",")[0].trim();
  return req.socket?.remoteAddress || "unknown";
}

// 每分钟 30 次，够一个人连点搜索框，挡不住分布式的——够用了
function rateLimited(ip) {
  const now = Date.now();
  const arr = (hits.get(ip) || []).filter((t) => now - t < 60000);
  if (arr.length >= 30) {
    hits.set(ip, arr);
    return true;
  }
  arr.push(now);
  hits.set(ip, arr);
  if (hits.size > 2000) hits.clear();     // 防止 Map 无限长
  return false;
}

function cors(req, res, allow) {
  const origin = req.headers.origin || "";
  if (origin && allow.includes(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Max-Age", "86400");
  return !origin || allow.includes(origin);
}

function readBody(req) {
  if (req.body) return typeof req.body === "string" ? req.body : JSON.stringify(req.body);
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

module.exports = async function handler(req, res) {
  const allow = (process.env.ALLOW_ORIGINS || DEFAULTS.allowOrigins)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const ok = cors(req, res, allow);
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  if (req.method === "GET") {
    res.status(200).json({ ok: true, model: process.env.EMBED_MODEL || DEFAULTS.model });
    return;
  }
  if (req.method !== "POST") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }
  if (!ok) {
    res.status(403).json({ error: "origin_not_allowed" });
    return;
  }

  const key = process.env.EMBED_API_KEY;
  if (!key) {
    res.status(500).json({ error: "missing_key", hint: "在 Vercel 环境变量里设置 EMBED_API_KEY" });
    return;
  }

  if (rateLimited(clientIp(req))) {
    res.status(429).json({ error: "rate_limited", retryAfter: 60 });
    return;
  }

  const d = today();
  if (d !== day) {
    day = d;
    dayCount = 0;
  }
  if (dayCount >= Number(process.env.DAILY_BUDGET || DEFAULTS.dailyBudget)) {
    res.status(429).json({ error: "daily_budget_exhausted" });
    return;
  }

  let text = "";
  try {
    const raw = await readBody(req);
    text = (JSON.parse(raw || "{}").text || "").trim();
  } catch (e) {
    res.status(400).json({ error: "bad_body" });
    return;
  }
  if (!text) {
    res.status(400).json({ error: "empty_text" });
    return;
  }
  if (text.length > MAX_CHARS) {
    res.status(413).json({ error: "text_too_long", max: MAX_CHARS });
    return;
  }

  const ck = text.toLowerCase();
  if (cache.has(ck)) {
    const hit = cache.get(ck);
    res.setHeader("X-Cache", "HIT");
    res.status(200).json({ ...hit, cached: true });
    return;
  }

  const model = process.env.EMBED_MODEL || DEFAULTS.model;
  const base = process.env.EMBED_API_BASE || DEFAULTS.base;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), UPSTREAM_TIMEOUT);

  try {
    dayCount += 1;
    const r = await fetch(base, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify({ model, input: text, encoding_format: "float" }),
      signal: ctrl.signal,
    });
    if (!r.ok) {
      const detail = (await r.text()).slice(0, 300);
      res.status(502).json({ error: "upstream_error", status: r.status, detail });
      return;
    }
    const j = await r.json();
    const vec = j?.data?.[0]?.embedding;
    if (!Array.isArray(vec) || !vec.length) {
      res.status(502).json({ error: "bad_upstream_payload" });
      return;
    }
    const rounded = vec.map((x) => Math.round(x * 1e5) / 1e5);
    const payload = { v: rounded, dim: rounded.length, model };
    if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value);
    cache.set(ck, payload);
    res.setHeader("X-Cache", "MISS");
    res.status(200).json({ ...payload, cached: false });
  } catch (e) {
    const aborted = e?.name === "AbortError";
    res.status(aborted ? 504 : 502).json({ error: aborted ? "upstream_timeout" : "upstream_failed" });
  } finally {
    clearTimeout(timer);
  }
};
