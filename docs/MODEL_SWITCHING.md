# Model switching (stage splat / GLB)

## Purpose

- Point the viewer at the **current** city model without hardcoding filenames.
- Switch stage by **device** (PC 3DGS vs mobile GLB) and optional URL override.

## R2 layout

```
models/
  city_gs/
    latest.json
    20261011_120000_point_cloud.ply
  city_glb/
    latest.json
    scramble.glb
```

### `latest.json` schema

```json
{
  "version": 1,
  "kind": "city_gs",
  "asset": "models/city_gs/20261011_120000_point_cloud.ply",
  "format": "ply",
  "created_at": "2026-10-11T12:00:00Z",
  "iterations": 15000,
  "notes": "optional"
}
```

| Field | Required | Notes |
|-------|----------|--------|
| `kind` | yes | `city_gs` \| `city_glb` |
| `asset` | yes | R2 object key |
| `format` | yes | `ply` \| `splat` \| `glb` |
| `created_at` | yes | ISO-8601 UTC |
| `iterations` | no | training only |

## Batch behavior (`city_gs`)

After successful `.ply` upload in `batch_3dgs.py`:

1. Upload ply to `models/city_gs/{timestamp}_{name}.ply`
2. Write/overwrite `models/city_gs/latest.json` pointing at that key
3. Controlled by YAML:

```yaml
workflow:
  upload_ply: true
  update_latest: true
paths:
  ply_r2_prefix: "models/city_gs/"
```

## Worker API

```
GET /api/models/latest?kind=city_gs
GET /api/models/latest?kind=city_glb
  → latest.json body (404 if missing)

GET /api/models/object?key=models/city_gs/....ply
  → binary stream from R2 (validate key starts with models/)
```

Security: reject `..` and keys outside `models/`.

## Viewer selection logic

```text
function resolveKind(searchParams, isMobile):
  if searchParams.stage in {city_gs, city_glb}: return that
  if isMobile: return city_glb
  return city_gs
```

Then:

1. `GET /api/models/latest?kind=...`
2. Load asset via `/api/models/object?key=...` or public R2 URL if configured later

## PC vs mobile

| Kind | Consumer | Library (suggested) |
|------|----------|---------------------|
| `city_gs` | Desktop | splat mesh viewer / Gaussian splat WebGL loader |
| `city_glb` | Mobile | three.js GLTFLoader |

Exact loader choice is an implementation detail of the viewer issue; this doc only defines **discovery and switching**.

## Out of scope

- Day/night multiple stages (can add `kind=city_gs_night` later with same schema)
- CDN cache invalidation beyond Cache-Control on GET

## Acceptance criteria

- [ ] Successful batch updates `models/city_gs/latest.json`
- [ ] `GET /api/models/latest?kind=city_gs` returns JSON with valid `asset`
- [ ] `GET /api/models/object` streams file for keys under `models/`
- [ ] Invalid keys → 400
- [ ] Missing latest → 404
- [ ] Viewer (or minimal test page) can resolve kind by mobile UA or `?stage=`
