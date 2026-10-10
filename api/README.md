# API

Cloudflare Workers の HTTP API。実装はリポジトリ直下の `src/index.ts`。

## Endpoints

### `POST /api/upload`

写真を R2 に保存する。

- Content-Type: `multipart/form-data`
- フィールド: `file`（jpeg / png / webp、最大 15MB）

**成功例**

```json
{
  "ok": true,
  "key": "photos/2026-10-10/1728567890123_a1b2c3d4e5f6.jpg",
  "size": 1234567,
  "contentType": "image/jpeg",
  "url": "/api/photos/photos%2F2026-10-10%2F..."
}
```

### `GET /api/photos`

クエリ: `prefix`（default `photos/`）, `limit`（default 50, max 100）

```json
{
  "prefix": "photos/",
  "count": 2,
  "truncated": false,
  "objects": [
    {
      "key": "photos/2026-10-10/....jpg",
      "size": 1234567,
      "uploaded": "2026-10-10T06:00:00.000Z",
      "url": "/api/photos/..."
    }
  ]
}
```

### `GET /api/photos/:key`

画像バイナリ。`key` は URL エンコード可。

## 保存キー

```
photos/YYYY-MM-DD/<timestamp>_<id>.{jpg|png|webp}
```

## 今後（未実装）

- presigned URL（Colab 用）
- `models/` 配信
- placement 一覧
