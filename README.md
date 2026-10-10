# shibuya-scramble-crossing

渋谷スクランブル交差点を、多数の写真から **3D Gaussian Splatting (3DGS)** で再構築するプロジェクト。

## コンセプト

- **Cloudflare** 上で動く Web サービス（Workers + R2）
- 写真投稿を受け付ける
- **R2 → Colab** で 3DGS 学習（中継ストレージなし）
- **JS のみ** でビューア表示

詳細は [PRD.md](./PRD.md) を参照。

## パイプライン

```
[Browser] 写真アップロード
    ↓
[Workers] → R2 photos/
    ↓
[Colab] R2 から直接取得 → COLMAP → 3DGS → .ply
    ↓
[JS Viewer] 表示
```

## 現状

### Phase 0 — 写真アップロード

```bash
npm install
npm run dev      # http://localhost:8787
npm run deploy
```

手順: [docs/setup-r2.md](./docs/setup-r2.md)

### Phase 1 — Colab 学習

R2 の写真を Colab で取得して 3DGS 学習:

- 手順書: [docs/colab-r2-3dgs.md](./docs/colab-r2-3dgs.md)
- ノートブック: [colab/r2_3dgs_template.ipynb](./colab/r2_3dgs_template.ipynb)

## ドキュメント

- [PRD.md](./PRD.md)
- [docs/setup-r2.md](./docs/setup-r2.md)
- [docs/colab-r2-3dgs.md](./docs/colab-r2-3dgs.md)
