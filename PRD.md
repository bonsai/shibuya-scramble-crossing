# PRD: Shibuya Scramble Crossing 3DGS

**Product Requirements Document**  
最終更新: 2026-10-10（設計更新: R2 → Colab 直送）

---

## 1. プロダクト概要

### 1.1 ビジョン

渋谷スクランブル交差点を、クラウドソースされた多数の写真から **3D Gaussian Splatting (3DGS)** で再構築し、ブラウザ上で誰でも自由に視点を動かせる Web 体験を提供する。

### 1.2 コンセプト

- 時間差でいろんな人が集合して写真を投稿（クラウドソース）
- 写真投稿 → **R2 保存** → **Colab で 3DGS 学習** → **JS のみで表示**
- インフラは **Cloudflare** 中心（Workers + R2）
- 学習は **Colab / Kaggle** 上で Python 実行
- **中継ストレージなし**（MEGA / GCS 等は使わない）。Colab が R2 から直接取得する

### 1.3 対象ユーザー

- 渋谷交差点に興味がある一般ユーザー（写真投稿・3D閲覧）
- 開発者・実験者（パイプライン改善・モデル再学習）

---

## 2. ゴールと非ゴール

### 2.1 ゴール（MVP）

| # | 項目 | 優先度 | 状態 |
|---|------|--------|------|
| G1 | 写真アップロードサイト（Web） | P0 | 実装済み（最小） |
| G2 | R2 への写真保存 | P0 | 実装済み |
| G3 | 3DGS 学習パイプライン（Colab、R2 直取得） | P0 | テンプレート済み |
| G4 | JS のみの 3DGS ビューア | P0 | 未着手 |
| G5 | 学習済みモデルの配信（R2 `models/`） | P0 | 未着手 |
| G6 | ローカル運用支援（任意・MCP 等） | P2 | 後回し可 |

### 2.2 非ゴール（初期段階ではやらない）

- リアルタイム学習
- 完全自動の人マスク除去
- モバイル専用アプリ
- 高頻度の再学習（日次など）
- 中継用クラウド（MEGA / GCS 等）の常設
- ローカルから画像ファイルを Colab に直接アップロードする運用（原則 R2 経由）

---

## 3. システムアーキテクチャ

```
[Browser]
   │ 写真アップロード / 3D閲覧
   ▼
[Cloudflare Workers]
   │
   ├─► [R2]  photos/   （原本・永続）
   │         models/   （学習済み .ply / .splat）
   │
   └─► [Viewer]  JS のみで 3DGS 表示

[Google Colab / Kaggle]
   │ boto3 等で R2 から直接ダウンロード
   ├─ COLMAP（カメラ姿勢推定）
   ├─ 3DGS 学習（train.py）
   └─ .ply 出力
         │
         ▼（任意）
   [R2 models/ にアップロード] または ローカル保存
```

### 3.1 コンポーネント役割

| コンポーネント | 役割 | 技術 |
|----------------|------|------|
| 写真投稿 | アップロード UI / API | Cloudflare Workers + 静的 HTML |
| オブジェクトストレージ | 写真原本・モデル保管（**唯一の永続ストレージ**） | Cloudflare R2 |
| 学習実行 | R2 取得 → COLMAP → 3DGS | Google Colab / Kaggle |
| ビューア | 3DGS 表示 | JS（gsplat.js / Spark.js 等） |
| デプロイ | API + フロント | TypeScript / Workers（将来 Go も可） |

### 3.2 やらないこと（設計上の明示）

- ローカル PC に学習用画像を溜めて Colab に送る主経路にはしない
- MEGA 等の一時ステージングは採用しない（必要なら将来オプション）

---

## 4. データ設計

### 4.1 R2 構成（永続・唯一）

```
r2://shibuya-scramble/
├── photos/
│   ├── YYYY-MM-DD/
│   │   ├── <timestamp>_<id>.jpg
│   │   └── ...
│   └── ...
├── models/
│   ├── YYYY-MM-DD_vN/
│   │   ├── point_cloud.ply
│   │   ├── metadata.json
│   │   └── ...
│   └── ...
└── meta/
    └── index.json          # 将来用
```

アップロード API の保存キー例:

```
photos/2026-10-10/1728567890123_a1b2c3d4e5f6.jpg
```

### 4.2 画像保持方針

| 場所 | 保持内容 | 削除タイミング |
|------|----------|----------------|
| **R2** | 全写真 + 学習済みモデル | 基本残す |
| **Colab ディスク** | 学習中の `input/` と出力 | セッション終了で消える（問題なし） |

- 1回の学習目安: 100〜200 枚
- 中継ストレージの容量制限（20GB 等）は **考慮不要**（R2 + Colab エフェメラルのみ）

---

## 5. 3DGS 加工パイプライン

### 5.1 手順概要

1. **写真収集** — ブラウザ → Workers → R2 `photos/`
2. **Colab で R2 から取得** — boto3（S3 互換）で `input/` に並べる
3. **COLMAP** — カメラ位置・姿勢推定
4. **3DGS 学習** — `train.py`
5. **出力** — `point_cloud.ply`
6. **配信** — R2 `models/` へ（任意）→ JS ビューア

手順の詳細・セル全文: [docs/colab-r2-3dgs.md](./docs/colab-r2-3dgs.md)  
ノートブック: [colab/r2_3dgs_template.ipynb](./colab/r2_3dgs_template.ipynb)

### 5.2 COLMAP（概要）

- 公式 `convert.py` を優先
- 失敗時は CPU 強制（`SiftExtraction.use_gpu 0`）や解像度制限（`max_image_size 1600`）
- 無料 T4 不安定時は [3DGS-Colab-Free-T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4) を参考

### 5.3 3DGS 学習

```bash
python train.py -s <data> -m <output> \
  --iterations 15000 \
  --save_iterations 7000 15000
```

- プレビュー: 7,000 iterations
- 本番品質: 30,000 iterations

### 5.4 参考実装

- 公式: [graphdeco-inria/gaussian-splatting](https://github.com/graphdeco-inria/gaussian-splatting)
- Colab 安定化: [tianxingleo/3DGS-Colab-Free-T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4)

---

## 6. Colab ↔ R2 接続

### 6.1 方式（現行）

| 方式 | 内容 | 備考 |
|------|------|------|
| **boto3 + R2 API トークン** | Colab から list / download /（任意）upload | 実装済み（テンプレート） |

### 6.2 将来オプション

| 方式 | 内容 | 目的 |
|------|------|------|
| Presigned URL | Workers が一時 URL を発行 | Colab に長期キーを置かない |
| バッチ zip API | Workers が複数枚をまとめて返す | 取得簡略化（サイズ制限に注意） |

### 6.3 認証注意

- R2 API トークンはノートブックに直書きせず、可能なら Colab シークレットや実行時入力にする
- トークンは Git にコミットしない

---

## 7. ビューア要件

- **JS のみ**で動作（追加ネイティブ依存なし）
- 対応フォーマット: `.ply` / `.splat` / `.spz`
- 候補ライブラリ:
  - [gsplat.js](https://github.com/huggingface/gsplat.js)
  - Spark.js
  - SuperSplat 等
- モデルは R2 `models/` から配信（Workers 経由 or 公開バケット）

---

## 8. デプロイ構成

| レイヤ | 技術 | 状態 |
|--------|------|------|
| アップロード API + UI | Workers (`src/index.ts`) + `public/` | 実装済み |
| ストレージ | R2 `shibuya-scramble` | 要バケット作成 |
| 学習 | Colab テンプレート | ドキュメント済み |
| ビューア | 未実装 | Phase 2 |
| 認証 | 当面なし | 本番前に制限追加 |

セットアップ: [docs/setup-r2.md](./docs/setup-r2.md)

---

## 9. 運用フロー（日常）

1. ユーザーが写真を投稿 → R2 `photos/`
2. 学習するとき Colab を開く
3. 設定セルに R2 認証・`R2_PREFIX`・`MAX_IMAGES` を入れる
4. ダウンロード → COLMAP → `train.py`
5. `.ply` をダウンロード、または R2 `models/` に upload
6. ビューアが `models/` を参照して表示（Phase 2）

ローカルマシンは **開発・デプロイ・ドキュメント** 用。学習用画像の中継はしない。

---

## 10. 成功指標（MVP）

| 指標 | 目標 |
|------|------|
| 写真投稿 | ブラウザから R2 に保存できる |
| R2 → Colab | 100 枚以上を取得できる |
| 1回の学習完走 | `.ply` が生成される |
| ビューア表示 | ブラウザで回転・ズーム可能 |
| 運用 | Colab だけで学習を完結できる |

---

## 11. リスクと対策

| リスク | 対策 |
|--------|------|
| Colab 無料枠の不安定さ | 安定化ノートブック / Pro / 枚数・解像度を落とす |
| COLMAP 失敗 | CPU モード、リサイズ、枚数削減 |
| R2 認証の扱い | シークレット管理、将来 presign |
| 人の写り込みノイズ | 将来 SAM 等（非ゴール） |
| 写真の角度不足 | 投稿ガイド・最低枚数の案内 |
| 公開アップロードの悪用 | レート制限・認証（本番前） |

---

## 12. ロードマップ

### Phase 0 — 基盤
- [x] リポジトリ初期化
- [x] PRD
- [x] 写真アップロード API / UI 最小実装
- [ ] R2 バケット作成（運用者が実施）
- [ ] `wrangler deploy` で本番公開

### Phase 1 — 学習パイプライン
- [x] Colab テンプレート（R2 直取得）
- [x] 手順書 `docs/colab-r2-3dgs.md`
- [ ] 実データで 1 回の 3DGS 学習完走
- [ ] （任意）Workers に presign API

### Phase 2 — ビューア
- [ ] JS ビューア組み込み
- [ ] R2 `models/` から配信

### Phase 3 — 改善
- [ ] バッチ選択（日付・最新 N 枚）
- [ ] 投稿の認証・レート制限
- [ ] 投稿体験の改善

---

## 13. 参考リンク

- [gaussian-splatting (公式)](https://github.com/graphdeco-inria/gaussian-splatting)
- [gsplat.js](https://github.com/huggingface/gsplat.js)
- [3DGS Colab Free T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4)
- [Cloudflare R2 Docs](https://developers.cloudflare.com/r2/)
- 本リポジトリ: [docs/colab-r2-3dgs.md](./docs/colab-r2-3dgs.md) / [docs/setup-r2.md](./docs/setup-r2.md)

---

## 14. 用語

| 用語 | 意味 |
|------|------|
| 3DGS | 3D Gaussian Splatting |
| COLMAP | Structure-from-Motion / MVS ツール |
| R2 | Cloudflare のオブジェクトストレージ（本プロジェクトの永続置き場） |
| バッチ | 1回の学習に使う写真セット（R2 上の prefix + 枚数で指定） |
