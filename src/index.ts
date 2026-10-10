/**
 * Shibuya Scramble Crossing — photo upload + Colab tunnel proxy
 *
 * Routes:
 *   GET  /           → UI
 *   POST /api/upload → R2
 *   GET  /api/photos
 *   GET  /api/photos/:key
 *   POST /api/colab/register  → Colab がトンネル URL を登録
 *   GET  /api/colab           → 登録情報
 *   GET  /api/colab/status    → トンネルへプロキシ
 *   POST /api/colab/batch     → トンネルへプロキシ
 *   POST /api/colab/stop
 */

export interface Env {
  PHOTOS: R2Bucket;
  ASSETS: Fetcher;
}

const MAX_SIZE = 15 * 1024 * 1024;
const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
]);

const COLAB_META_KEY = "control/colab.json";

function corsHeaders(): HeadersInit {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Colab-Token",
  };
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(),
    },
  });
}

function todayPrefix(): string {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `photos/${y}-${m}-${day}`;
}

function randomId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
}

function extFromType(type: string): string {
  if (type.includes("png")) return "png";
  if (type.includes("webp")) return "webp";
  return "jpg";
}

type ColabMeta = {
  tunnel_url: string;
  token?: string | null;
  registered_at: string;
};

async function readColabMeta(env: Env): Promise<ColabMeta | null> {
  const obj = await env.PHOTOS.get(COLAB_META_KEY);
  if (!obj) return null;
  try {
    return (await obj.json()) as ColabMeta;
  } catch {
    return null;
  }
}

async function writeColabMeta(env: Env, meta: ColabMeta): Promise<void> {
  await env.PHOTOS.put(COLAB_META_KEY, JSON.stringify(meta, null, 2), {
    httpMetadata: { contentType: "application/json" },
  });
}

async function proxyColab(
  env: Env,
  path: string,
  method: string,
  body?: string
): Promise<Response> {
  const meta = await readColabMeta(env);
  if (!meta?.tunnel_url) {
    return json({ error: "Colab tunnel not registered" }, 503);
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (meta.token) {
    headers["Authorization"] = `Bearer ${meta.token}`;
  }

  const target = `${meta.tunnel_url.replace(/\/$/, "")}${path}`;
  try {
    const res = await fetch(target, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : body ?? "{}",
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") || "application/json",
        ...corsHeaders(),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return json({ error: "tunnel unreachable", detail: message }, 502);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    if (path === "/api/upload" && request.method === "POST") {
      return handleUpload(request, env);
    }
    if (path === "/api/photos" && request.method === "GET") {
      return handleListPhotos(request, env);
    }
    if (path.startsWith("/api/photos/") && request.method === "GET") {
      const key = decodeURIComponent(path.slice("/api/photos/".length));
      return handleGetPhoto(key, env);
    }

    // --- Colab tunnel ---
    if (path === "/api/colab/register" && request.method === "POST") {
      return handleColabRegister(request, env);
    }
    if (path === "/api/colab" && request.method === "GET") {
      const meta = await readColabMeta(env);
      if (!meta) return json({ registered: false });
      return json({
        registered: true,
        tunnel_url: meta.tunnel_url,
        registered_at: meta.registered_at,
        has_token: Boolean(meta.token),
      });
    }
    if (path === "/api/colab/status" && request.method === "GET") {
      return proxyColab(env, "/status", "GET");
    }
    if (path === "/api/colab/batch" && request.method === "POST") {
      const body = await request.text();
      return proxyColab(env, "/batch", "POST", body || "{}");
    }
    if (path === "/api/colab/stop" && request.method === "POST") {
      return proxyColab(env, "/stop", "POST", "{}");
    }

    if (env.ASSETS) {
      return env.ASSETS.fetch(request);
    }
    return json({ error: "Not found" }, 404);
  },
};

async function handleColabRegister(request: Request, env: Env): Promise<Response> {
  try {
    const data = (await request.json()) as {
      tunnel_url?: string;
      token?: string | null;
    };
    const tunnel_url = (data.tunnel_url || "").trim();
    if (!tunnel_url.startsWith("https://")) {
      return json({ error: "tunnel_url must be https://..." }, 400);
    }
    const meta: ColabMeta = {
      tunnel_url,
      token: data.token || null,
      registered_at: new Date().toISOString(),
    };
    await writeColabMeta(env, meta);
    return json({ ok: true, ...meta, token: undefined, has_token: Boolean(meta.token) });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return json({ error: "register failed", detail: message }, 500);
  }
}

async function handleUpload(request: Request, env: Env): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") || "";
    if (!contentType.includes("multipart/form-data")) {
      return json({ error: "Content-Type must be multipart/form-data" }, 400);
    }

    const form = await request.formData();
    const file = form.get("file");

    if (!file || !(file instanceof File)) {
      return json({ error: "field 'file' is required" }, 400);
    }
    if (!ALLOWED_TYPES.has(file.type)) {
      return json(
        { error: `Unsupported type: ${file.type}. Use jpeg/png/webp` },
        400
      );
    }
    if (file.size > MAX_SIZE) {
      return json({ error: `File too large (max ${MAX_SIZE / 1024 / 1024}MB)` }, 400);
    }

    const ext = extFromType(file.type);
    const key = `${todayPrefix()}/${Date.now()}_${randomId()}.${ext}`;

    await env.PHOTOS.put(key, file.stream(), {
      httpMetadata: { contentType: file.type },
      customMetadata: {
        originalName: file.name || "",
        uploadedAt: new Date().toISOString(),
      },
    });

    return json({
      ok: true,
      key,
      size: file.size,
      contentType: file.type,
      url: `/api/photos/${encodeURIComponent(key)}`,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return json({ error: "Upload failed", detail: message }, 500);
  }
}

async function handleListPhotos(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const prefix = url.searchParams.get("prefix") || "photos/";
  const limit = Math.min(Number(url.searchParams.get("limit") || 50), 100);

  const listed = await env.PHOTOS.list({ prefix, limit });
  const objects = listed.objects.map((o) => ({
    key: o.key,
    size: o.size,
    uploaded: o.uploaded?.toISOString?.() ?? null,
    url: `/api/photos/${encodeURIComponent(o.key)}`,
  }));

  return json({
    prefix,
    count: objects.length,
    truncated: listed.truncated,
    objects,
  });
}

async function handleGetPhoto(key: string, env: Env): Promise<Response> {
  if (!key || key.includes("..")) {
    return json({ error: "Invalid key" }, 400);
  }
  const obj = await env.PHOTOS.get(key);
  if (!obj) return json({ error: "Not found" }, 404);

  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("etag", obj.httpEtag);
  headers.set("Cache-Control", "public, max-age=86400");
  Object.entries(corsHeaders()).forEach(([k, v]) => headers.set(k, v));
  return new Response(obj.body, { headers });
}
