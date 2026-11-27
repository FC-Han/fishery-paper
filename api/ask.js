/**
 * POST /api/ask —— 文献问答（RAG）的生成代理
 *
 * 前端先用站内向量（emb.bin）召回相关论文，再把「召回结果 + 问题」发到这里，
 * 由 DeepSeek 生成带引用的中文回答。key 只存在服务端。
 *
 * 请求：POST {
 *   "q": "大黄鱼养殖最近的病害研究有什么进展",
 *   "docs": [{ "t": 标题, "s": 中文速览, "j": 期刊, "d": 日期, "u": 链接 }]
 * }
 * 响应：{ "a": "……[1][2]……", "model": "deepseek-chat", "usage": {...} }
 *
 * 环境变量（Vercel → Settings → Environment Variables）：
 *   DEEPSEEK_API_KEY  必填
 *   DEEPSEEK_BASE     默认 https://api.deepseek.com
 *   DEEPSEEK_MODEL    默认 deepseek-chat
 *   ALLOW_ORIGINS     允许的前端来源（与 embed.js 共用一套即可）
 *   ASK_DAILY_BUDGET  单实例每天最多放行多少次（默认 300）
 */

const DEFAULTS = {
  base: "https://api.deepseek.com",
  model: "deepseek-chat",
  allowOrigins: "https://fc-han.github.io,https://fishery-paper.vercel.app,http://localhost:8000,http://127.0.0.1:8000",
  dailyBudget: 300,
};

const MAX_Q = 300;          // 问题长度
const MAX_DOCS = 10;        // 最多带几篇文献进 context
const DOC_CHARS = 520;      // 每篇摘要截断，控制 token
const MAX_BODY = 32000;
const UPSTREAM_TIMEOUT = 45000;

// 允许多个变量名：复制粘贴变量名时常混进零宽字符或尾随空格，Vercel 那边校验不出来，
// 但运行时就是读不到。多认几个写法，等于给这类事故留条后路。
const KEY_NAMES = ["DEEPSEEK_API_KEY", "DEEPSEEK_KEY", "DEEPSEEK_APIKEY", "DS_API_KEY"];
function readKey() {
  for (const n of KEY_NAMES) {
    const v = (process.env[n] || "").trim();
    if (v) return v;
  }
  return "";
}

const hits = new Map();
let day = "";
let dayCount = 0;

const SYSTEM = [
  "你是渔业与水产科学文献助手，服务对象是研究人员。",
  "只依据用户消息里给出的【参考文献】回答问题，不要引入外部知识或编造数据。",
  "回答用简体中文，先给一句结论，再分点展开（每点不超过 2 句），最后可用一句话点出研究空白。",
  "每个论点后面用 [1]、[2] 标注依据的文献编号，编号必须来自给出的参考文献。",
  "如果文献不足以回答，直接说「现有文献没有覆盖这个问题」，并指出最接近的几篇讲了什么。",
  "不要重复罗列文献标题，界面上已经展示；不要使用 Markdown 表格。",
].join("\n");

function today() {
  return new Date().toISOString().slice(0, 10);
}

function clientIp(req) {
  const fwd = req.headers["x-forwarded-for"];
  if (typeof fwd === "string" && fwd) return fwd.split(",")[0].trim();
  return req.socket?.remoteAddress || "unknown";
}

// 生成比 embedding 贵得多，限流收紧到每分钟 6 次
function rateLimited(ip) {
  const now = Date.now();
  const arr = (hits.get(ip) || []).filter((t) => now - t < 60000);
  if (arr.length >= 6) {
    hits.set(ip, arr);
    return true;
  }
  arr.push(now);
  hits.set(ip, arr);
  if (hits.size > 2000) hits.clear();
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

function buildContext(docs) {
  return docs
    .map((d, i) => {
      const body = String(d.s || "").slice(0, DOC_CHARS).replace(/\s+/g, " ").trim();
      return `[${i + 1}] ${d.t || "（无标题）"}\n期刊/日期：${d.j || "—"} · ${d.d || "—"}\n摘要：${body || "（无摘要）"}`;
    })
    .join("\n\n");
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
    // 健康检查：默认只回是否配置好，不暴露任何部署细节。
    // 加 ?debug=1 才返回定位用的字段（项目 ID、commit、变量名清单）——
    // 排查「变量加了却读不到」时用，平时不该长期公开。
    const k = readKey();
    const out = {
      ok: true,
      model: process.env.DEEPSEEK_MODEL || DEFAULTS.model,
      key: k ? "set" : "MISSING",
    };
    if (!k) {
      out.hint = "服务端没读到 DEEPSEEK_API_KEY；也可以在站点「问一问」面板里临时填自己的 Key";
    }
    if (/[?&]debug=1(&|$)/.test(req.url || "")) {
      const sysPrefix = /^(VERCEL|AWS|NODE|npm|LAMBDA|NOW_|_$|TZ|HOME|PATH|LANG|SHELL|CI|PORT|PWD|HOSTNAME)/;
      out.keyLength = k ? k.length : 0;
      out.project = process.env.VERCEL_PROJECT_ID || null;
      out.deploymentUrl = process.env.VERCEL_URL || null;
      out.env = process.env.VERCEL_ENV || null;
      out.branch = process.env.VERCEL_GIT_COMMIT_REF || null;
      out.commit = (process.env.VERCEL_GIT_COMMIT_SHA || "").slice(0, 7) || null;
      out.userEnvNames = Object.keys(process.env).filter((n) => !sysPrefix.test(n)).sort();
    }
    res.status(200).json(out);
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

  // 注意：Vercel 的环境变量是部署时注入的，加完变量不重新部署，这里永远读不到。
  // 允许多个名字，是为了绕过「变量名里混进了零宽字符 / 尾随空格」这类复制粘贴事故。
  if (rateLimited(clientIp(req))) {
    res.status(429).json({ error: "rate_limited", retryAfter: 60 });
    return;
  }

  const d = today();
  if (d !== day) {
    day = d;
    dayCount = 0;
  }
  if (dayCount >= Number(process.env.ASK_DAILY_BUDGET || DEFAULTS.dailyBudget)) {
    res.status(429).json({ error: "daily_budget_exhausted" });
    return;
  }

  let q = "";
  let docs = [];
  let clientKey = "";
  try {
    const raw = await readBody(req);
    const body = JSON.parse(raw || "{}");
    q = String(body.q || "").trim();
    docs = Array.isArray(body.docs) ? body.docs.slice(0, MAX_DOCS) : [];
    // 浏览器自带的 key：只用于本次请求，不落库、不写日志
    const ck = String(body.k || "").trim();
    if (ck.length >= 20 && ck.length <= 200) clientKey = ck;
  } catch (e) {
    res.status(400).json({ error: "bad_body" });
    return;
  }

  // 服务端变量优先；没有就用浏览器临时带来的（用户在「问一问」面板里自填）
  const key = readKey() || clientKey;
  if (!key) {
    res.status(500).json({
      error: "missing_key",
      hint: "服务端没读到 DEEPSEEK_API_KEY，你也没有在页面上填自己的 Key",
    });
    return;
  }
  if (!q) {
    res.status(400).json({ error: "empty_question" });
    return;
  }
  if (q.length > MAX_Q) {
    res.status(413).json({ error: "question_too_long", max: MAX_Q });
    return;
  }
  if (!docs.length) {
    res.status(400).json({ error: "no_docs" });
    return;
  }

  const model = process.env.DEEPSEEK_MODEL || DEFAULTS.model;
  const base = (process.env.DEEPSEEK_BASE || DEFAULTS.base).replace(/\/+$/, "");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), UPSTREAM_TIMEOUT);

  try {
    dayCount += 1;
    const r = await fetch(`${base}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: SYSTEM },
          {
            role: "user",
            content: `【参考文献】\n${buildContext(docs)}\n\n【问题】\n${q}`,
          },
        ],
        temperature: 0.3,
        max_tokens: 900,
        stream: false,
      }),
      signal: ctrl.signal,
    });
    if (!r.ok) {
      const detail = (await r.text()).slice(0, 300);
      // 401/403 是 key 本身有问题，和「key 没注入」不是一回事，分开报
      const authIssue = r.status === 401 || r.status === 403;
      res.status(502).json({
        error: authIssue ? "upstream_auth" : "upstream_error",
        status: r.status,
        detail,
        hint: authIssue ? "key 无效或没权限，检查是否复制完整、有无多余空格、账户余额" : "",
      });
      return;
    }
    const j = await r.json();
    const answer = j?.choices?.[0]?.message?.content || "";
    if (!answer.trim()) {
      res.status(502).json({ error: "empty_answer" });
      return;
    }
    res.status(200).json({ a: answer, model, usage: j.usage || null });
  } catch (e) {
    const aborted = e?.name === "AbortError";
    res.status(aborted ? 504 : 502).json({ error: aborted ? "upstream_timeout" : "upstream_failed" });
  } finally {
    clearTimeout(timer);
  }
};
