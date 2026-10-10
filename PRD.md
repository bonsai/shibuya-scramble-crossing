# PRD: Shibuya Scramble Crossing 3DGS

**Product Requirements Document**  
最終更新: 2026-10-10

---

## 1. プロダクト概要

### 1.1 ビジョン

渋谷スクランブル交差点を、クラウドソースされた多数の写真から **3D Gaussian Splatting (3DGS)** で再構築し、ブラウザ上で誰でも自由に視点を動かせる Web 体験を提供する。

### 1.2 コンセプト

- 時間差でいろんな人が集合して写真を投稿（クラウドソース）
- 写真投稿 → 解析 → 3DGS 構築 → JS のみで表示
- インフラは **Cloudflare** 中心（Workers + Pages + R2）
- 学習は **Colab / Kaggle** 上で Python 実行
- 運用コストを抑え、一時ストレージは **20GB 以下** で回す

### 1.3 対象ユーザー

- 渋谷交差点に興味がある一般ユーザー（写真投稿・3D閲覧）
- 開発者・実験者（パイプライン改善・モデル再学習）

---

## 2. ゴールと非ゴール

### 2.1 ゴール（MVP）

| # | 項目 | 優先度 |
|---|------|--------|
| G1 | 写真アップロードサイト（Web） | P0 |
| G2 | R2 への写真保存 | P0 |
| G3 | 3DGS 学習パイプライン（Colab） | P0 |
| G4 | JS のみの 3DGS ビューア | P0 |
| G5 | 学習済みモデルの配信 | P0 |
| G6 | ローカル MCP によるバッチ準備・運用支援 | P1 |

### 2.2 非ゴール（初期段階ではやらない）

- リアルタイム学習
- 完全自動の人マスク除去
- モバイル専用アプリ
- 高頻度の再学習（日次など）

---

## 3. システムアーキテクチャ

```
[Browser]
   │ 写真アップロード / 3D閲覧
   ▼
[Cloudflare Pages + Workers]
   │
   ├─► [R2]  photos/   （原本・永続）
   │         models/   （学習済み .ply / .splat）
   │
   └─► [Viewer]  JS のみで 3DGS 表示

[ローカル MCP Server]
   │ R2 から必要バッチを抽出
   ▼
[MEGA]  一時ステージング（≤20GB）
   │
   ▼
[Google Colab]
   ├─ COLMAP（カメラ姿勢推定）
   ├─ 3DGS 学習
   └─ .ply 出力
   │
   ▼
[R2 models/ に保存] → MEGA 一時データ削除
```

### 3.1 コンポーネント役割

| コンポーネント | 役割 | 技術 |
|----------------|------|------|
| 写真投稿サイト | アップロード UI / API | Cloudflare Pages + Workers |
| オブジェクトストレージ | 写真原本・モデル保管 | Cloudflare R2 |
| 一時ステージング | 学習用バッチ | MEGA（無料20GB） |
| 学習実行環境 | COLMAP + 3DGS | Google Colab / Kaggle |
| オーケストレーション | バッチ作成・削除・モデル転送 | ローカル MCP (FastMCP) |
| ビューア | 3DGS 表示 | JS（gsplat.js / Spark.js 等） |
| デプロイ | フロント・API | Go / TypeScript / Cloudflare |

---

## 4. データ設計

### 4.1 R2 構成（永続）

```
r2://shibuya-scramble/
├── photos/
│   ├── YYYY-MM-DD/
│   │   ├── img_xxx.jpg
│   │   └── ...
│   └── ...
├── models/
│   ├── YYYY-MM-DD_vN/
│   │   ├── point_cloud.ply
│   │   ├── metadata.json
│   │   └── ...
│   └── ...
└── meta/
    └── index.json
```

### 4.2 MEGA 構成（一時・20GB以内）

```
/Root/shibuya-temp/
├── batch_YYYYMMDD_HHMM/
│   ├── input/              # COLMAP 用画像
│   │   ├── 0001.jpg
│   │   └── ...
│   └── batch_info.json
└── ...（学習後削除）
```

### 4.3 画像保持方針

| 場所 | 保持内容 | 削除タイミング |
|------|----------|----------------|
| R2 | 全写真 + 学習済みモデル | 基本残す |
| MEGA | 1学習分のバッチのみ | 学習成功後すぐ削除 |
| Colab | 作業中のみ | セッション終了時 |

- 1バッチ目安: 100〜200枚 ≈ 0.4〜1.2 GB
- 常時使用量を 5GB 以下に抑える設計

---

## 5. 3DGS 加工パイプライン

### 5.1 手順概要

1. **写真収集** — R2 に蓄積
2. **バッチ準備** — MCP で R2 → MEGA
3. **COLMAP** — カメラ位置・姿勢推定（Structure-from-Motion）
4. **3DGS 学習** — Gaussian Splatting 最適化
5. **出力** — `.ply` / `.splat`
6. **配信** — R2 に保存 → JS ビューアで表示
7. **クリーンアップ** — MEGA 一時データ削除

### 5.2 COLMAP（典型コマンド）

```bash
colmap feature_extractor \
  --database_path database.db \
  --image_path input \
  --ImageReader.single_camera 1 \
  --SiftExtraction.use_gpu 0

colmap exhaustive_matcher \
  --database_path database.db \
  --SiftMatching.use_gpu 0

colmap mapper \
  --database_path database.db \
  --image_path input \
  --output_path distorted/sparse

colmap image_undistorter \
  --image_path input \
  --input_path distorted/sparse/0 \
  --output_path . \
  --output_type COLMAP \
  --max_image_size 1600
```

または公式 `convert.py` を利用。

### 5.3 3DGS 学習

```bash
python train.py -s /path/to/data \
  -m /path/to/output \
  --iterations 15000 \
  --save_iterations 7000 15000
```

- プレビュー: 7,000 iterations
- 本番品質: 30,000 iterations

### 5.4 推奨環境・参考

- Colab 無料 T4 向け安定化: [tianxingleo/3DGS-Colab-Free-T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4)
- カスタムデータ用テンプレート: [benyoon1/gaussian-splat-colab](https://github.com/benyoon1/gaussian-splat-colab)
- 公式: [graphdeco-inria/gaussian-splatting](https://github.com/graphdeco-inria/gaussian-splatting)

---

## 6. ローカル MCP サーバー仕様

### 6.1 目的

AI エージェント（Cursor / Claude / Grok 等）から R2・MEGA を操作し、学習バッチの準備と後処理を自然言語で行えるようにする。

### 6.2 ツール一覧

| ツール | 説明 |
|--------|------|
| `list_r2_photos` | R2 の写真一覧取得 |
| `prepare_batch` | R2 → MEGA に学習用バッチ作成 |
| `cleanup_mega_batch` | MEGA 一時バッチ削除 |
| `upload_model_to_r2` | 学習済みモデルを R2 に保存 |

### 6.3 技術スタック

- FastMCP
- boto3（R2 = S3 互換）
- mega.py
- python-dotenv

### 6.4 実装場所（予定）

```
mcp/
├── server.py
├── requirements.txt
└── .env.example
```

---

## 7. ビューア要件

- **JS のみ**で動作（追加ネイティブ依存なし）
- 対応フォーマット: `.ply` / `.splat` / `.spz`
- 候補ライブラリ:
  - [gsplat.js](https://github.com/huggingface/gsplat.js)
  - Spark.js
  - SuperSplat 等
- Cloudflare Pages で静的配信

---

## 8. デプロイ構成（予定）

| レイヤ | 技術 |
|--------|------|
| フロントエンド | TypeScript + Cloudflare Pages |
| API / アップロード | Cloudflare Workers（必要に応じて Go） |
| ストレージ | R2 |
| 認証 | 当面なし or Cloudflare Access（任意） |

---

## 9. 運用フロー（日常）

1. ユーザーが写真を投稿 → R2 `photos/` に蓄積
2. 学習タイミングで MCP に指示  
   「最新 150 枚でバッチを作って」
3. MCP が `prepare_batch` 実行 → MEGA に配置
4. Colab ノートブックで COLMAP + 3DGS 実行
5. `.ply` をダウンロード
6. MCP で `upload_model_to_r2` → R2 `models/` へ
7. MCP で `cleanup_mega_batch` → MEGA 削除
8. ビューアが新しいモデルを配信

---

## 10. 成功指標（MVP）

| 指標 | 目標 |
|------|------|
| 写真投稿 | 動作すること |
| 1回の学習完走 | 100枚以上で .ply 生成 |
| ビューア表示 | ブラウザで回転・ズーム可能 |
| 一時ストレージ | MEGA 使用量 20GB 以下を維持 |
| 運用手間 | MCP + Colab で手動でも回せる |

---

## 11. リスクと対策

| リスク | 対策 |
|--------|------|
| Colab 無料枠の不安定さ | 安定化ノートブック利用 / Pro 検討 |
| MEGA API の不安定さ | リトライ実装 / 将来 GCS へ切替可能に設計 |
| 人の写り込みノイズ | 将来 SAM 等でマスク（非ゴール） |
| 写真の角度不足 | 投稿ガイド・最低枚数の案内 |
| R2 / MEGA 認証漏洩 | `.env` 管理、Git にコミットしない |

---

## 12. ロードマップ（概略）

### Phase 0 — 基盤
- [x] リポジトリ初期化
- [ ] PRD 確定
- [ ] R2 バケット作成
- [ ] 写真アップロード API / UI 最小実装

### Phase 1 — 学習パイプライン
- [ ] ローカル MCP 実装
- [ ] Colab テンプレート整備
- [ ] 手動で 1 回の 3DGS 学習完走

### Phase 2 — ビューア
- [ ] JS ビューア組み込み
- [ ] R2 のモデルを配信

### Phase 3 — 改善
- [ ] バッチ選択ロジック（日付・品質）
- [ ] 一時ストレージを GCS に切替可能に
- [ ] 投稿体験の改善

---

## 13. 参考リンク

- [gaussian-splatting (公式)](https://github.com/graphdeco-inria/gaussian-splatting)
- [gsplat.js](https://github.com/huggingface/gsplat.js)
- [3DGS Colab Free T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4)
- [Cloudflare R2 Docs](https://developers.cloudflare.com/r2/)
- [FastMCP](https://github.com/jlowin/fastmcp)

---

## 14. 用語

| 用語 | 意味 |
|------|------|
| 3DGS | 3D Gaussian Splatting |
| COLMAP | Structure-from-Motion / MVS ツール |
| R2 | Cloudflare のオブジェクトストレージ |
| MCP | Model Context Protocol |
| バッチ | 1回の学習に使う写真セット |
