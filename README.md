# shibuya-scramble-crossing

渋谷スクランブル交差点を、多数の写真から **3D Gaussian Splatting (3DGS)** で再構築するプロジェクト。

## コンセプト

- **Cloudflare** 上で動く Web サービス（Workers + Pages + R2）
- 写真投稿を受け付ける
- 解析する
- 3DGS を構築する
- 時間差でいろんな人が集合して写真を投稿（クラウドソース）
- **JS のみ**

## アーキテクチャ（予定）

```
[Browser]  →  写真アップロード
       ↓
[Cloudflare Worker]  →  R2 に保存 + メタデータ記録
       ↓
[解析]  →  EXIF / 簡易特徴量 / クライアントサイド処理
       ↓
[十分な数が集まったら]  →  3DGS 構築（オフライン or 将来的に WebGPU）
       ↓
[Viewer]  →  JS のみで3DGS を表示
```

## 現状

リポジトリ初期化済み。実装はここから。
