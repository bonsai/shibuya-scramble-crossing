/**
 * Shibuya Scramble Crossing — minimal photo upload API + static UI
 *
 * Routes:
 *   GET  /           → アップロード UI（public/index.html）
 *   POST /api/upload → 写真を R2 に保存
 *   GET  /api/photos → 最近の写真一覧
 *   GET  /api/photos/:key → 写真の取得（プレビュー用）
 */

export interface Env {
  PHOTOS: R2Bucket;
  ASSETS: Fetcher;
}

const MAX_SIZE = 15 * 1024 * 1024; // 15MB
const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
]);

function corsHeaders(): HeadersInit {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // --- API ---
    if (path === "/api/upload" && request.method === "POST") {
      return handleUpload(request, env);
    }

    if (path === "/api/photos" && request.method === "GET") {
      return handleListPhotos(request, env);
    }

    // /api/photos/<key...> で画像を返す
    if (path.startsWith("/api/photos/") && request.method === "GET") {
      const key = decodeURIComponent(path.slice("/api/photos/".length));
      return handleGetPhoto(key, env);
    }

    // --- 静的アセット ---
    if (env.ASSETS) {
      return env.ASSETS.fetch(request);
    }

    return json({ error: "Not found" }, 404);
  },
};

async function handleUpload(request: Request, env: Env): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") || "";

    // multipart/form-data を想定
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
      httpMetadata: {
        contentType: file.type,
      },
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

  const listed = await env.PHOTOS.list({
    prefix,
    limit,
  });

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
  if (!obj) {
    return json({ error: "Not found" }, 404);
  }

  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("etag", obj.httpEtag);
  headers.set("Cache-Control", "public, max-age=86400");
  Object.entries(corsHeaders()).forEach(([k, v]) => headers.set(k, v));

  return new Response(obj.body, { headers });
}
