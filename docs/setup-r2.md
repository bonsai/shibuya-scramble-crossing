# R2 バケット作成 & デプロイ手順

## 1. 前提

- [Cloudflare アカウント](https://dash.cloudflare.com/)
- Node.js 18+
- Wrangler CLI（`npm i -g wrangler` またはプロジェクトローカル）

## 2. R2 バケット作成

```bash
npx wrangler login
npx wrangler r2 bucket create shibuya-scramble
```

ダッシュボードからも可: **R2** → **Create bucket** → 名前 `shibuya-scramble`

## 3. ローカル開発

```bash
npm install
npm run dev
```

ブラウザで `http://localhost:8787` を開く。

> ローカルでは R2 のシミュレーションが使われます。本番と同じバケットを使う場合は `wrangler.toml` の設定を確認してください。

## 4. デプロイ

```bash
npm run deploy
```

初回は R2 バインディングの許可を求められることがあります。

## 5. API

| Method | Path | 説明 |
|--------|------|------|
| `POST` | `/api/upload` | `multipart/form-data` で `file` を送信 |
| `GET` | `/api/photos?prefix=photos/&limit=50` | 一覧 |
| `GET` | `/api/photos/<key>` | 画像本体 |

### アップロード例 (curl)

```bash
curl -X POST https://<your-worker>.workers.dev/api/upload \
  -F "file=@photo.jpg"
```

### レスポンス例

```json
{
  "ok": true,
  "key": "photos/2026-10-10/1728..._a1b2c3d4e5f6.jpg",
  "size": 1234567,
  "contentType": "image/jpeg",
  "url": "/api/photos/photos%2F2026-10-10%2F..."
}
```

## 6. 保存パス規約

```
photos/YYYY-MM-DD/<timestamp>_<random>.{jpg|png|webp}
```

PRD の R2 設計に準拠。

## 7. 制限（MVP）

- 最大 15MB / 枚
- jpeg / png / webp のみ
- 認証なし（公開アップロード）— 本番前に制限を追加すること
