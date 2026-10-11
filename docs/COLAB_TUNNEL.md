# Colab tunnel (CF UI → GPU batch)

## Purpose

Operate training from the Cloudflare-hosted UI while the heavy job runs on Colab/Kaggle.

## Flow

1. User starts Colab runtime + `tunnel_server.py`
2. Process listens on `127.0.0.1:8765`
3. `cloudflared tunnel --url http://127.0.0.1:8765` yields `https://*.trycloudflare.com`
4. Server `POST {CF_BASE_URL}/api/colab/register` with `{ tunnel_url, token? }`
5. Worker stores meta at R2 key `control/colab.json`
6. UI calls Worker proxy routes; Worker forwards to tunnel

## Colab endpoints

| Method | Path | Auth | Behavior |
|--------|------|------|----------|
| GET | `/health` | no | `{ ok: true }` |
| GET | `/status` | token if set | status, log_tail |
| POST | `/batch` | token if set | body: `{ force?, dry_run?, skip_train?, prefix? }` → 202 |
| POST | `/stop` | token if set | terminate running process |

## Worker endpoints

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/api/colab/register` | save tunnel URL + optional token |
| GET | `/api/colab` | registration info (no raw token) |
| GET | `/api/colab/status` | proxy GET `/status` |
| POST | `/api/colab/batch` | proxy POST `/batch` |
| POST | `/api/colab/stop` | proxy POST `/stop` |

## Env (Colab)

| Var | Required |
|-----|----------|
| `R2_*` | yes for training |
| `CF_BASE_URL` | yes for auto-register |
| `COLAB_TOKEN` | optional shared secret |
| `BATCH_SCRIPT` / `BATCH_CONFIG` | optional paths |

## Failure modes

- Tunnel not registered → Worker returns 503
- Tunnel dead → 502
- Batch already running → 409 from Colab

## Security notes

- Quick tunnels are public URLs; prefer `COLAB_TOKEN`
- Do not put R2 secrets in the browser; only on Colab / Worker bindings
