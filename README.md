# shibuya-scramble-crossing

渋谷スクランブル交差点の写真を集め、**街は 3D・人は写真のまま**「ここにいた」を残す。

- **PC**: 3DGS の街  
- **スマホ**: 軽いポリゴンの街  
- **人**: 立体化せず、写真を空間に浮かせる  
- **データ**: Cloudflare R2 → Colab / Kaggle で学習

進捗は **[Issues](https://github.com/bonsai/shibuya-scramble-crossing/issues)**。

## アーキテクチャ（ハイブリッド方針）

「JS のみ」の制約を守りつつ、本格的な 3DGS 学習は GPU 環境に任せる。

1. **Cloudflare側（JS のみ）**
   - 写真投稿受付
   - R2 に保存
   - メタデータ管理・簡易解析
   - 十分集まったら「写真セットをエクスポート」

2. **Colab / Kaggle側（GPU）**
   - エクスポートした写真群を読み込む
   - COLMAP → 3DGS（gsplat / nerfstudio など）で構築
   - できた `.ply` / `.splat` をダウンロード

3. **再度 Cloudflare側**
   - 構築結果をアップロード
   - JS の 3DGS ビューアで公開

この分割により、エッジ環境では回せない重い学習を避けつつ、本番の 3DGS を実現できる。

## フォルダ

| パス | 役割 |
|------|------|
| `src/` | Cloudflare Workers（投稿 API） |
| `public/` | 投稿 UI |
| `api/` | API 仕様メモ・クライアント向け |
| `mcp/` | ローカル MCP（任意・運用支援） |
| `colab/` | R2→3DGS 学習ノートブック |

```bash
npm install && npm run dev
```

## Colab の結果（何ができるか）

`colab/r2_3dgs_template.ipynb` を最後まで通すと、だいたい次が出る。

| 成果物 | 場所の例 | 意味 |
|--------|----------|------|
| 学習用に並べた画像 | `/content/data/input/0001.jpg` … | R2 から落とした写真 |
| COLMAP のカメラ情報 | `sparse/0/` など | 各写真の位置・向き |
| **点群モデル** | `.../point_cloud/iteration_*/point_cloud.ply` | **街の 3DGS 本体** |

- **成功の目安**: `.ply` が1つできて、ビューアで建物・地面が分かること  
- **人**はにじんでも無視してよい（人はあとから写真パネルで載せる）  
- その `.ply` を PC 用の街 `models/city_gs/` に置く想定  
- スマホ用は Colab では作らない（別途 GLB）

詳細手順・チェックリストは Issue（Epic B）へ。
