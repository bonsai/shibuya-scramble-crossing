# shibuya-scramble-crossing

渋谷スクランブル交差点を、多数の写真から **3D Gaussian Splatting (3DGS)** で再構築するプロジェクト。

## コンセプト

- **Cloudflare** 上で動く Web サービス（Workers + Pages + R2）
- 写真投稿を受け付ける
- 解析する
- 3DGS を構築する
- 時間差でいろんな人が集合して写真を投稿（クラウドソース）
- **JS のみ** でビューア表示

詳細は [PRD.md](./PRD.md) を参照。

## 現状

### Phase 0 — 写真アップロード（実装済み）

- R2 への写真アップロード API（Workers）
- 最小アップロード UI（ドラッグ＆ドロップ）
- 最近の投稿一覧

```bash
npm install
npm run dev      # http://localhost:8787
npm run deploy   # 本番デプロイ
```

セットアップ手順: [docs/setup-r2.md](./docs/setup-r2.md)

### アーキテクチャ（予定）

```
[Browser]  →  写真アップロード
       ↓
[Cloudflare Worker]  →  R2 に保存 + メタデータ記録
       ↓
[解析]  →  EXIF / 簡易特徴量 / クライアントサイド処理
       ↓
[十分な数が集まったら]  →  3DGS 構築（Colab / オフライン）
       ↓
[Viewer]  →  JS のみで 3DGS を表示
```

## ドキュメント

- [PRD.md](./PRD.md) — 要件・パイプライン設計
- [docs/setup-r2.md](./docs/setup-r2.md) — R2 / デプロイ手順
