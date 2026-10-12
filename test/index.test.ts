import assert from "node:assert";
import test from "node:test";
import worker from "../src/index.ts";
import type { Env } from "../src/index.ts";

function createMockR2(store: Record<string, { body: string | Uint8Array; httpMetadata?: Record<string, string>; customMetadata?: Record<string, string> }>) {
  return {
    async get(key: string) {
      const item = store[key];
      if (!item) return null;
      const bodyStream = new ReadableStream({
        start(controller) {
          const bytes = typeof item.body === "string" ? new TextEncoder().encode(item.body) : item.body;
          controller.enqueue(bytes);
          controller.close();
        },
      });
      return {
        body: bodyStream,
        httpEtag: '"mock-etag"',
        async json() {
          if (typeof item.body === "string") {
            return JSON.parse(item.body);
          }
          return JSON.parse(new TextDecoder().decode(item.body));
        },
        async text() {
          if (typeof item.body === "string") {
            return item.body;
          }
          return new TextDecoder().decode(item.body);
        },
        writeHttpMetadata(headers: Headers) {
          if (item.httpMetadata?.contentType) {
            headers.set("content-type", item.httpMetadata.contentType);
          }
        },
      };
    },
    async put() {},
    async list() {
      return { objects: [], truncated: false };
    },
  } as unknown as R2Bucket;
}

test("GET /api/models/latest?kind=city_gs returns latest.json contents", async () => {
  const store = {
    "models/city_gs/latest.json": {
      body: JSON.stringify({
        version: 1,
        kind: "city_gs",
        asset: "models/city_gs/20261011_120000_point_cloud.ply",
        format: "ply",
        created_at: "2026-10-11T12:00:00Z",
      }),
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/models/latest?kind=city_gs");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { kind: string; asset: string };
  assert.strictEqual(body.kind, "city_gs");
  assert.strictEqual(body.asset, "models/city_gs/20261011_120000_point_cloud.ply");
});

test("GET /api/models/latest with missing or invalid kind -> 400 JSON", async () => {
  const env: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };

  // missing kind
  const req1 = new Request("https://example.com/api/models/latest");
  const res1 = await worker.fetch(req1, env);
  assert.strictEqual(res1.status, 400);
  assert.strictEqual(res1.headers.get("content-type"), "application/json; charset=utf-8");
  const body1 = await res1.json() as { error: string };
  assert.ok(body1.error);

  // invalid kind
  const req2 = new Request("https://example.com/api/models/latest?kind=other");
  const res2 = await worker.fetch(req2, env);
  assert.strictEqual(res2.status, 400);
  assert.strictEqual(res2.headers.get("content-type"), "application/json; charset=utf-8");
  const body2 = await res2.json() as { error: string };
  assert.ok(body2.error);
});

test("GET /api/models/latest with missing object -> 404 JSON", async () => {
  const env: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/models/latest?kind=city_gs");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 404);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { error: string };
  assert.ok(body.error);
});

test("GET /api/models/object streams valid key under models/", async () => {
  const store = {
    "models/city_gs/20261011_120000_point_cloud.ply": {
      body: "binary ply data",
      httpMetadata: { contentType: "application/octet-stream" },
    },
    "models/city_gs/latest.json": {
      body: JSON.stringify({ version: 1 }),
      httpMetadata: { contentType: "application/json" },
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };

  // versioned asset key keeps a long-lived immutable cache
  const req1 = new Request("https://example.com/api/models/object?key=models/city_gs/20261011_120000_point_cloud.ply");
  const res1 = await worker.fetch(req1, env);
  assert.strictEqual(res1.status, 200);
  assert.strictEqual(res1.headers.get("content-type"), "application/octet-stream");
  assert.strictEqual(res1.headers.get("cache-control"), "public, max-age=31536000, immutable");
  const text1 = await res1.text();
  assert.strictEqual(text1, "binary ply data");

  // mutable latest.json key must NOT be immutable (short revalidating cache, e.g. no-cache)
  const req2 = new Request("https://example.com/api/models/object?key=models/city_gs/latest.json");
  const res2 = await worker.fetch(req2, env);
  assert.strictEqual(res2.status, 200);
  assert.ok(!res2.headers.get("cache-control")?.includes("immutable"));
  assert.strictEqual(res2.headers.get("cache-control"), "no-cache");
});

test("GET /api/models/object rejects invalid key -> 400 JSON", async () => {
  const env: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };

  const badKeys = [
    "photos/test.jpg",               // not starting with models/
    "models/../secret",              // contains ..
    "/models/test.ply",             // leading slash
    "models\\test.ply",             // backslash
    "models/test\0.ply",            // null byte
    "",                              // empty
  ];

  for (const key of badKeys) {
    const req = new Request(`https://example.com/api/models/object?key=${encodeURIComponent(key)}`);
    const res = await worker.fetch(req, env);
    assert.strictEqual(res.status, 400, `Key ${key} should be rejected with 400`);
    assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
    const body = await res.json() as { error: string };
    assert.ok(body.error);
  }
});

test("GET /api/models/object missing key in R2 -> 404 JSON", async () => {
  const env: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/models/object?key=models/city_gs/missing.ply");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 404);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { error: string };
  assert.ok(body.error);
});

test("GET /api/placements returns placements/index.json", async () => {
  const store = {
    "placements/index.json": {
      body: JSON.stringify({
        version: 1,
        export_key: "placements/20261011_120000.json",
        count: 1,
      }),
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { export_key: string };
  assert.strictEqual(body.export_key, "placements/20261011_120000.json");
});

test("GET /api/placements missing -> 404 JSON", async () => {
  const env: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 404);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { error: string };
  assert.ok(body.error);
});

test("GET /api/placements/latest returns full placements array via export_key", async () => {
  const placementsArray = [
    {
      id: "0001",
      photo_key: "photos/2026-10-11/123.jpg",
      local_name: "0001.jpg",
      position: [1.0, 2.0, 3.0],
      rotation: [0, 0, 0, 1],
    },
  ];
  const store = {
    "placements/index.json": {
      body: JSON.stringify({
        version: 1,
        export_key: "placements/20261011_120000.json",
        count: 1,
      }),
    },
    "placements/20261011_120000.json": {
      body: JSON.stringify(placementsArray),
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements/latest");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as Array<{ id: string }>;
  assert.ok(Array.isArray(body));
  assert.strictEqual(body.length, 1);
  assert.strictEqual(body[0].id, "0001");
});

test("GET /api/placements/latest missing index, export_key, or export object -> 404 JSON", async () => {
  // Case 1: missing index
  const env1: Env = { PHOTOS: createMockR2({}), ASSETS: {} as Fetcher };
  const res1 = await worker.fetch(new Request("https://example.com/api/placements/latest"), env1);
  assert.strictEqual(res1.status, 404);
  assert.strictEqual(res1.headers.get("content-type"), "application/json; charset=utf-8");

  // Case 2: index missing export_key, null export_key, empty string, or non-string
  const invalidKeys = [null, "", 123, undefined];
  for (const exportKey of invalidKeys) {
    const env2: Env = {
      PHOTOS: createMockR2({
        "placements/index.json": { body: JSON.stringify({ version: 1, export_key: exportKey }) },
      }),
      ASSETS: {} as Fetcher,
    };
    const res2 = await worker.fetch(new Request("https://example.com/api/placements/latest"), env2);
    assert.strictEqual(res2.status, 404, `export_key=${String(exportKey)} should yield 404`);
    assert.strictEqual(res2.headers.get("content-type"), "application/json; charset=utf-8");
  }

  // Case 3: export object missing in R2
  const env3: Env = {
    PHOTOS: createMockR2({
      "placements/index.json": { body: JSON.stringify({ version: 1, export_key: "placements/missing.json" }) },
    }),
    ASSETS: {} as Fetcher,
  };
  const res3 = await worker.fetch(new Request("https://example.com/api/placements/latest"), env3);
  assert.strictEqual(res3.status, 404);
  assert.strictEqual(res3.headers.get("content-type"), "application/json; charset=utf-8");
});

test("GET /api/placements/latest rejects export_key pointing at control/colab.json -> 400 and no secrets leaked", async () => {
  const store = {
    "placements/index.json": {
      body: JSON.stringify({
        version: 1,
        export_key: "control/colab.json",
      }),
    },
    "control/colab.json": {
      body: JSON.stringify({
        tunnel_url: "https://secret-tunnel.example.com",
        token: "super-secret-token-12345",
      }),
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements/latest");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 400);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const text = await res.text();
  assert.ok(!text.includes("super-secret-token-12345"));
  assert.ok(!text.includes("secret-tunnel.example.com"));
  const body = JSON.parse(text) as { error: string };
  assert.ok(body.error);
});

test("GET /api/placements/latest rejects export_key with path traversal -> 400", async () => {
  const store = {
    "placements/index.json": {
      body: JSON.stringify({
        version: 1,
        export_key: "placements/../control/colab.json",
      }),
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements/latest");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 400);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { error: string };
  assert.ok(body.error);
});

test("GET /api/placements/latest with corrupt placements/index.json -> 500 JSON", async () => {
  const store = {
    "placements/index.json": {
      body: "invalid-json-{",
    },
  };
  const env: Env = { PHOTOS: createMockR2(store), ASSETS: {} as Fetcher };
  const req = new Request("https://example.com/api/placements/latest");
  const res = await worker.fetch(req, env);

  assert.strictEqual(res.status, 500);
  assert.strictEqual(res.headers.get("content-type"), "application/json; charset=utf-8");
  const body = await res.json() as { error: string };
  assert.ok(body.error);
});
