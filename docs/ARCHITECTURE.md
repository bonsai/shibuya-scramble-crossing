# Architecture

## Goal

渋谷スクランブル交差点で、**街は 3D・人は写真のまま**「ここにいた」を残す。

| 層 | PC | モバイル |
|------|----|----------|
| 街（ステージ） | 3D Gaussian Splatting | 軽量 GLB（ポリゴン） |
| 人 | 立体化しない。写真パネルを空間に配置 | 同左 |

## System diagram

```
[Browser UI]
  │ upload photos
  │ trigger batch (optional)
  ▼
[Cloudflare Worker + R2]
  photos/YYYY-MM-DD/*.jpg
  models/city_gs/*.ply + latest.json
  models/city_glb/*.glb + latest.json
  placements/*.json + index.json
  control/colab.json          # tunnel registration
  │
  │ cloudflared tunnel (when Colab is up)
  ▼
[Colab / Kaggle GPU]
  batch_3dgs.py  → COLMAP + 3DGS train
  tunnel_server.py → /batch /status /stop
```

## Constraints

- **Edge (CF)**: JS/TS only. No GPU training.
- **Training**: Colab/Kaggle only.
- **Viewer**: JS only in browser.
- **Secrets**: R2 keys never committed. Env vars / Colab secrets only.

## Repo map

| Path | Role |
|------|------|
| `src/index.ts` | Worker: upload, photos, colab proxy, (future) models/placements API |
| `public/index.html` | Upload UI + Colab control panel |
| `colab/batch_3dgs.py` | R2 download → COLMAP → train → upload ply |
| `colab/batch_config.yaml` | Thresholds + workflow |
| `colab/tunnel_server.py` | Colab HTTP API + cloudflared |
| `docs/` | Design contracts for implementers (Jules etc.) |

## Design docs

- [PLACEMENTS.md](./PLACEMENTS.md) — pose export + photo panels
- [MODEL_SWITCHING.md](./MODEL_SWITCHING.md) — latest.json + stage switch
- [COLAB_TUNNEL.md](./COLAB_TUNNEL.md) — CF UI ↔ Colab via tunnel

## Non-goals (for now)

- Full human mesh reconstruction
- Real-time multi-user presence
- On-Worker 3DGS training
