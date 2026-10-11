# shibuya-scramble-crossing

渋谷スクランブル交差点の写真を集め、**街は 3D・人は写真のまま**「ここにいた」を残す。

- **PC**: 3DGS の街  
- **スマホ**: 軽いポリゴンの街  
- **人**: 立体化せず、写真を空間に浮かせる  
- **データ**: Cloudflare R2 → Colab / Kaggle で学習

進捗は **[Issues](https://github.com/bonsai/shibuya-scramble-crossing/issues)**。

## 設計ドキュメント（実装契約）

外部エージェント（Jules 等）に委託するときは、Issue 本文より **先にここを読む**。

| Doc | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 全体構成・制約・リポマップ |
| [docs/PLACEMENTS.md](./docs/PLACEMENTS.md) | COLMAP pose → placements JSON |
| [docs/MODEL_SWITCHING.md](./docs/MODEL_SWITCHING.md) | `latest.json` ・ステージ切替 |
| [docs/COLAB_TUNNEL.md](./docs/COLAB_TUNNEL.md) | CF UI ↔ Colab トンネル |

## アーキテクチャ（ハイブリッド）

1. **Cloudflare（JS のみ）** … 投稿・R2・プロキシ・配信  
2. **Colab / Kaggle（GPU）** … COLMAP + 3DGS  
3. **ビューア（JS）** … PC=3DGS / モバイル=GLB + 写真パネル  

## フォルダ

| パス | 役割 |
|------|------|
| `src/` | Cloudflare Workers |
| `public/` | 投稿 UI + Colab 操作 |
| `colab/` | バッチ・トンネル・YAML |
| `docs/` | 設計契約 |
| `api/` | API メモ |
| `mcp/` | 任意 MCP |

```bash
npm install && npm run dev
```
