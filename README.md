# shibuya-scramble-crossing

渋谷スクランブル交差点の **街** を 3D で見せ、投稿写真を **「ここにいた」** として空間に残すプロジェクト。

詳細な進捗・作業項目は **GitHub Issues（カンバン）** のみで管理する。ドキュメントはこの README と Issue 以外に増やさない。

---

## 方針（PRD 要約）

| レイヤ | 内容 |
|--------|------|
| **街（PC）** | 自前 **3DGS**（がっつり） |
| **街（スマホ）** | **ポリゴン GLB**（あっさり）。Poly Haven（CC0）部品 + 簡易交差点 |
| **人** | 3D でつながない。**写真パネル**として浮かせる |
| **データ** | 写真・モデルは **Cloudflare R2** のみ。学習は **Colab が R2 から直接取得** |

```
投稿 → R2 photos/
         ├─ Colab → 3DGS → models/city_gs/     （PC）
         └─ GLB  → models/city_low/            （モバイル）
                    ↓
              Viewer（端末で街を切替 + 写真パネル）
```

---

## 現状カンバン

Issue の **Status** プロジェクト／ラベルで更新する。ここは概要のみ。

| 列 | 内容 |
|----|------|
| **Backlog** | 未着手の Epic / タスク Issue |
| **Ready** | 今スプリントでやる |
| **In progress** | 作業中 |
| **Done** | 完了 |

### Epic 一覧（Issue 化）

| Epic | 内容 | いま |
|------|------|------|
| A 基盤 | R2・デプロイ・アップロード確認 | コードあり・運用未 |
| B 街 3DGS | Colab で `city_gs` を1本 | テンプレあり・学習未 |
| C モバイル GLB | Poly Haven + 簡易交差点 | 未 |
| D 浮く写真 | パネル・拡大・photos 連携 | 未 |
| E PC ビューア | 3DGS + パネル | 未 |
| F 切替 | 端末判定 PC/モバイル | 未 |
| G 改善 | 認証・UX 等 | 後回し |

→ **[Issues](https://github.com/bonsai/shibuya-scramble-crossing/issues)** をカンバンの実体とする。

### 推奨着手順

1. A（R2 本番で投稿できる）
2. C → D → F（スマホで「街＋ここにいた」）
3. B → E（PC を 3DGS に）

---

## リポジトリ構成（コード）

```
src/index.ts          Workers（upload / list / get）
public/index.html     投稿 UI
wrangler.toml         R2 バインド
colab/r2_3dgs_template.ipynb   R2→COLMAP→3DGS
```

旧 `PRD.md` / `TASKS.md` / `docs/*` は廃止。内容は本 README と Issue に集約。

---

## クイックスタート

### アップロード API（Workers）

```bash
npm install
npx wrangler login
npx wrangler r2 bucket create shibuya-scramble
npm run dev      # http://localhost:8787
npm run deploy
```

| Method | Path | 説明 |
|--------|------|------|
| POST | `/api/upload` | `multipart/form-data` の `file` |
| GET | `/api/photos` | 一覧 |
| GET | `/api/photos/<key>` | 画像 |

保存先: `photos/YYYY-MM-DD/<timestamp>_<id>.{jpg,png,webp}`

### Colab で街 3DGS

1. R2 API トークン（Object Read）を用意
2. `colab/r2_3dgs_template.ipynb` を開く（VS Code なら公式 Google Colab 拡張で Kernel=Colab）
3. Account ID / Key と `R2_PREFIX` / `MAX_IMAGES` を設定して上から実行
4. 出力 `.ply` → 後で `models/city_gs/` へ

人物の復元品質は問わない（街の器ができれば OK）。

---

## 非ゴール（初期）

- 人物の立体つなぎ合わせ
- MEGA 等の中継ストレージ
- ドキュメントファイルの追加（README と Issue のみ）

---

## License / 権利メモ

- 投稿写真・自前 3DGS: プロジェクト運用に従う
- モバイル部品: Poly Haven は CC0。交差点一式は Poly Haven に無いため自作 GLB
