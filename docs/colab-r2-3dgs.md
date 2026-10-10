# Colab: R2 からダウンロードして 3DGS 学習

写真は Cloudflare R2 にあり、Colab が直接取得して COLMAP → 3DGS 学習する流れです。
ローカルや MEGA への中継はしません。

```
R2 (photos/)  →  Colab  →  COLMAP  →  train.py  →  .ply
```

---

## 前提

1. R2 バケット `shibuya-scramble` に写真が入っている  
   （`photos/YYYY-MM-DD/...` 形式。Workers の `/api/upload` で投稿したもの）
2. R2 の **S3 互換 API トークン**（Access Key / Secret Key）を用意  
   Dashboard → R2 → Manage R2 API Tokens → Create API token  
   権限: Object Read（学習後にモデルを上げるなら Object Read & Write）
3. Colab で **GPU ランタイム**（T4 以上推奨）を選択

---

## Colab セル（上から順に実行）

### 0. 設定

```python
# ===== 設定（ここだけ書き換える）=====
R2_ACCOUNT_ID = "your_account_id"          # Cloudflare Account ID
R2_ACCESS_KEY_ID = "your_access_key"
R2_SECRET_ACCESS_KEY = "your_secret_key"
R2_BUCKET = "shibuya-scramble"

# 取得対象（例: 特定日 / 全体）
R2_PREFIX = "photos/"          # or "photos/2026-10-10/"
MAX_IMAGES = 150               # 学習に使う枚数上限

DATA_DIR = "/content/data"
OUTPUT_DIR = "/content/output"
ITERATIONS = 15000             # プレビュー 7k / 本番 30k
```

> ノートブックを共有する場合は、キーをセルに直書きせず  
> Colab の「シークレット」や一時入力にしてください。

---

### 1. 依存関係 + R2 からダウンロード

```python
!pip install -q boto3 plyfile

import boto3
from pathlib import Path
from botocore.config import Config

input_dir = Path(DATA_DIR) / "input"
input_dir.mkdir(parents=True, exist_ok=True)

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

# 一覧取得（ページネーション簡易版）
keys = []
continuation = None
while True:
    kwargs = {"Bucket": R2_BUCKET, "Prefix": R2_PREFIX, "MaxKeys": 1000}
    if continuation:
        kwargs["ContinuationToken"] = continuation
    resp = s3.list_objects_v2(**kwargs)
    for obj in resp.get("Contents", []):
        k = obj["Key"]
        if k.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            keys.append(k)
    if not resp.get("IsTruncated"):
        break
    continuation = resp.get("NextContinuationToken")

keys = keys[:MAX_IMAGES]
print(f"対象: {len(keys)} 枚 (prefix={R2_PREFIX})")

if not keys:
    raise RuntimeError("R2 に画像がありません。prefix とバケットを確認してください。")

for i, key in enumerate(keys, 1):
    ext = Path(key).suffix.lower() or ".jpg"
    if ext == ".jpeg":
        ext = ".jpg"
    dest = input_dir / f"{i:04d}{ext}"
    s3.download_file(R2_BUCKET, key, str(dest))
    if i % 20 == 0 or i == len(keys):
        print(f"  downloaded {i}/{len(keys)}")

print("✅ R2 からの取得完了 →", input_dir)
print("枚数:", len(list(input_dir.glob("*"))))
```

---

### 2. gaussian-splatting セットアップ

```python
%cd /content
!git clone --recursive -q https://github.com/graphdeco-inria/gaussian-splatting
%cd /content/gaussian-splatting

!pip install -q submodules/diff-gaussian-rasterization
!pip install -q submodules/simple-knn
```

CUDA やビルドで失敗する場合は、事前ビルド wheel を使う方法もあります（camenduru 配布など）。

---

### 3. COLMAP（カメラ推定）

`convert.py` は `DATA_DIR/input` を想定します。

```python
# COLMAP インストール（重い。初回のみ）
!apt-get -qq update
!apt-get -qq install -y colmap > /dev/null

# データパスを gaussian-splatting から参照しやすくする
!mkdir -p /content/gaussian-splatting/data
!rm -rf /content/gaussian-splatting/data/input
!ln -s /content/data/input /content/gaussian-splatting/data/input

%cd /content/gaussian-splatting
!python convert.py -s /content/gaussian-splatting/data
```

**無料 T4 で COLMAP が落ちる場合**

- `convert.py` 内相当を CPU 強制（`SiftExtraction.use_gpu 0`）にする
- または [3DGS-Colab-Free-T4](https://github.com/tianxingleo/3DGS-Colab-Free-T4) の COLMAP 手順を流用
- 画像を長辺 1600px 程度にリサイズしてから再実行

手動 COLMAP の例:

```bash
colmap feature_extractor \
  --database_path /content/data/database.db \
  --image_path /content/data/input \
  --ImageReader.single_camera 1 \
  --SiftExtraction.use_gpu 0

colmap exhaustive_matcher \
  --database_path /content/data/database.db \
  --SiftMatching.use_gpu 0

mkdir -p /content/data/distorted/sparse
colmap mapper \
  --database_path /content/data/database.db \
  --image_path /content/data/input \
  --output_path /content/data/distorted/sparse

colmap image_undistorter \
  --image_path /content/data/input \
  --input_path /content/data/distorted/sparse/0 \
  --output_path /content/data \
  --output_type COLMAP \
  --max_image_size 1600
```

成功すると `sparse/0/cameras.bin` などができます。

---

### 4. 3DGS 学習

```python
%cd /content/gaussian-splatting

!python train.py \
  -s /content/gaussian-splatting/data \
  -m {OUTPUT_DIR} \
  --iterations {ITERATIONS} \
  --save_iterations 7000 {ITERATIONS}

print("✅ 学習完了")
!find {OUTPUT_DIR} -name "*.ply" -print
```

出力例:

```
/content/output/point_cloud/iteration_15000/point_cloud.ply
```

---

### 5. （任意）学習済み .ply を R2 にアップロード

Write 権限のあるトークンが必要です。

```python
from datetime import datetime

ply_candidates = list(Path(OUTPUT_DIR).rglob("point_cloud.ply"))
if not ply_candidates:
    raise FileNotFoundError(".ply が見つかりません")

ply_path = sorted(ply_candidates, key=lambda p: p.stat().st_mtime)[-1]
model_name = datetime.utcnow().strftime("%Y-%m-%d_v1")
r2_key = f"models/{model_name}/point_cloud.ply"

s3.upload_file(str(ply_path), R2_BUCKET, r2_key)
print("✅ uploaded:", r2_key)
```

---

### 6. ローカルへダウンロード

```python
from google.colab import files
ply = sorted(Path(OUTPUT_DIR).rglob("point_cloud.ply"), key=lambda p: p.stat().st_mtime)[-1]
files.download(str(ply))
```

---

## トラブルシュート

| 症状 | 対処 |
|------|------|
| R2 で Access Denied | トークン権限・Account ID・バケット名を確認 |
| 画像 0 枚 | `R2_PREFIX` が `photos/` になっているか、実キーを Dashboard で確認 |
| COLMAP 失敗 | CPU モード、解像度下げ、枚数を 50〜100 に減らす |
| CUDA / ビルドエラー | 事前ビルド wheel、または別ノートブック（camenduru / Free-T4） |
| OOM | `--iterations` を減らす、画像リサイズ、`data_factor` 相当の縮小 |

---

## 次のステップ

1. 取得した `.ply` を JS ビューア（gsplat.js 等）で表示
2. Workers に presigned URL API を足し、Colab にキーを置かない運用にする
3. バッチ選択（日付・枚数）を自動化
