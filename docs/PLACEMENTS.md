# Placements (position estimation)

## Purpose

After COLMAP runs in the training batch, export each registered camera pose so the viewer can place photo panels (「ここにいた」) in the same coordinate frame as the city 3DGS.

## Coordinate frame

- Use **COLMAP / gaussian-splatting data coordinate frame** as-is.
- Do not re-center or scale in v1 unless the viewer requires a documented transform.
- If a transform is applied later, record it once in `placements/index.json` under `transform`.

## R2 layout

```
placements/
  index.json                 # manifest of latest export
  20261011_120000.json       # one export batch (array of placements)
```

### `placements/index.json`

```json
{
  "version": 1,
  "updated_at": "2026-10-11T12:00:00Z",
  "export_key": "placements/20261011_120000.json",
  "count": 120,
  "source": "colmap",
  "model_ref": "models/city_gs/20261011_120000_point_cloud.ply",
  "transform": null
}
```

### Each placement object (inside export file)

```json
{
  "id": "0042",
  "photo_key": "photos/2026-10-11/1728..._abc.jpg",
  "local_name": "0042.jpg",
  "position": [1.23, 0.45, -6.78],
  "rotation": [0.0, 0.0, 0.0, 1.0],
  "fov_deg": 60.0,
  "source": "colmap",
  "created_at": "2026-10-11T12:00:00Z"
}
```

| Field | Type | Notes |
|-------|------|--------|
| `position` | `[x,y,z]` number | COLMAP camera center (or document if using another convention) |
| `rotation` | `[qw,qx,qy,qz]` | Unit quaternion, world-from-camera or camera-from-world — **pick one and document in code comment** |
| `photo_key` | string \| null | R2 object key when mapping is known |
| `local_name` | string | Filename used during training (`0042.jpg`) |
| `fov_deg` | number \| null | From COLMAP camera params when available |

## Mapping local file → R2 key

Training renames downloads to `0001.jpg`, `0002.jpg`, ...  
Batch must keep a side map written at download time, e.g.:

```
/content/data/input/r2_key_map.json
{
  "0001.jpg": "photos/2026-10-11/....jpg",
  "0002.jpg": "photos/2026-10-10/....jpg"
}
```

Use this map when writing `photo_key`.

## Implementation plan (batch)

1. In `download_photos`, write `r2_key_map.json`.
2. After COLMAP `convert.py` succeeds, read poses from gaussian-splatting/COLMAP sparse model:
   - Prefer text model if present (`images.txt`, `cameras.txt`)
   - Else parse binary or use a small helper already common in the ecosystem
3. Build placement list; upload export JSON + update `index.json`.
4. Gate with YAML:

```yaml
workflow:
  export_placements: true
```

## API (Worker) — later but contract now

```
GET /api/placements
  → { index fields + optional inline items or url to export_key }

GET /api/placements/latest
  → full array from export_key object
```

Serve via R2 get; CORS same as photos.

## Viewer usage (downstream)

- Load stage splat/GLB.
- Load placements.
- For each item with `photo_key`, fetch image URL `/api/photos/{key}` and draw a textured plane (billboard or fixed orientation from `rotation`).

## Out of scope

- Localizing photos that were **not** in the COLMAP set
- Manual placement UI
- Bundle adjustment re-run on Worker

## Acceptance criteria

- [ ] After a successful train path, R2 has `placements/*.json` and `placements/index.json`
- [ ] At least one placement has non-null `position` and `rotation`
- [ ] When key map exists, `photo_key` is populated for mapped images
- [ ] `export_placements: false` skips upload
- [ ] Document quaternion convention in code comment next to writer
