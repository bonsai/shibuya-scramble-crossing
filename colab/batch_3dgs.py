#!/usr/bin/env python3
"""
Shibuya Scramble Crossing — 3DGS バッチ自動化スクリプト

用途:
  - R2 の写真数を確認し、条件を満たすとダウンロード
  - COLMAP + gaussian-splatting で学習（Colab / Kaggle 向け）
  - 完了後の .ply を R2 に戻すオプションあり

使い方（Colab）:
  1. このファイルを /content/batch_3dgs.py に置く
  2. 下記の環境変数を設定
  3. !python /content/batch_3dgs.py

必須環境変数:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
任意:
  R2_BUCKET, R2_PREFIX, MIN_IMAGES, MAX_IMAGES, DATA_DIR, OUTPUT_DIR,
  ITERATIONS, FORCE, UPLOAD_PLY
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------- 設定（環境変数 or 引数で上書き） ----------

def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def env_int(key: str, default: int) -> int:
    v = env(key)
    return int(v) if v else default


def env_bool(key: str, default: bool = False) -> bool:
    v = env(key).lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


R2_ACCOUNT_ID = env("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY")
R2_BUCKET = env("R2_BUCKET", "shibuya-scramble")
R2_PREFIX = env("R2_PREFIX", "photos/")
MIN_IMAGES = env_int("MIN_IMAGES", 80)      # これ以下ならバッチ中止
MAX_IMAGES = env_int("MAX_IMAGES", 150)     # 上限
DATA_DIR = Path(env("DATA_DIR", "/content/data"))
OUTPUT_DIR = Path(env("OUTPUT_DIR", "/content/output"))
ITERATIONS = env_int("ITERATIONS", 15000)
FORCE = env_bool("FORCE", False)            # True なら枚数条件を無視
UPLOAD_PLY = env_bool("UPLOAD_PLY", True)   # 完了後 .ply を R2 へ
GS_REPO = Path("/content/gaussian-splatting")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def die(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"ℹ️  {msg}")


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def get_s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "boto3"])
        import boto3
        from botocore.config import Config

    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        die("R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY を設定してください")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def list_photo_keys(s3, prefix: str) -> list[str]:
    keys: list[str] = []
    continuation = None
    while True:
        kwargs = {"Bucket": R2_BUCKET, "Prefix": prefix, "MaxKeys": 1000}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            k = obj["Key"]
            if k.lower().endswith(IMAGE_EXTS):
                keys.append(k)
        if not resp.get("IsTruncated"):
            break
        continuation = resp.get("NextContinuationToken")
    return keys


def decide_batch(keys: list[str]) -> tuple[bool, str]:
    """バッチ実行するか判定。(go, reason)"""
    n = len(keys)
    if FORCE:
        return True, f"FORCE=1 のため実行 (n={n})"
    if n < MIN_IMAGES:
        return False, f"写真数不足: {n} < MIN_IMAGES={MIN_IMAGES}"
    if n >= MIN_IMAGES:
        return True, f"条件達成: {n} 枚 >= {MIN_IMAGES}"
    return False, "unknown"


def download_photos(s3, keys: list[str], dest_dir: Path) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    # 既存を清掋（再実行時の残留防止）
    for p in dest_dir.glob("*"):
        if p.is_file():
            p.unlink()

    selected = keys[:MAX_IMAGES]
    for i, key in enumerate(selected, 1):
        ext = Path(key).suffix.lower() or ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"
        dest = dest_dir / f"{i:04d}{ext}"
        s3.download_file(R2_BUCKET, key, str(dest))
        if i % 20 == 0 or i == len(selected):
            print(f"  download {i}/{len(selected)}")
    return len(selected)


def ensure_gaussian_splatting() -> None:
    if GS_REPO.exists() and (GS_REPO / "train.py").exists():
        info("gaussian-splatting 既にあり")
        return
    info("gaussian-splatting を clone...")
    subprocess.check_call(
        ["git", "clone", "--recursive", "-q", "https://github.com/graphdeco-inria/gaussian-splatting", str(GS_REPO)]
    )
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "submodules/diff-gaussian-rasterization"], cwd=GS_REPO)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "submodules/simple-knn"], cwd=GS_REPO)


def ensure_colmap() -> None:
    try:
        subprocess.check_call(["colmap", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    info("COLMAP をインストール...")
    subprocess.check_call(["apt-get", "-qq", "update"])
    subprocess.check_call(["apt-get", "-qq", "install", "-y", "colmap"], stdout=subprocess.DEVNULL)


def run_colmap_and_train(input_dir: Path) -> Path | None:
    """convert.py → train.py。最終 .ply のパスを返す"""
    data_root = GS_REPO / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    link = data_root / "input"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(input_dir)

    info("COLMAP (convert.py)...")
    subprocess.check_call(
        [sys.executable, "convert.py", "-s", str(data_root)],
        cwd=GS_REPO,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    info(f"train.py (iterations={ITERATIONS})...")
    subprocess.check_call(
        [
            sys.executable,
            "train.py",
            "-s",
            str(data_root),
            "-m",
            str(OUTPUT_DIR),
            "--iterations",
            str(ITERATIONS),
            "--save_iterations",
            "7000",
            str(ITERATIONS),
        ],
        cwd=GS_REPO,
    )

    plys = sorted(OUTPUT_DIR.rglob("*.ply"))
    if not plys:
        return None
    # 最終イテレーションを優先
    return plys[-1]


def upload_ply(s3, ply_path: Path) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"models/city_gs/{ts}_{ply_path.name}"
    info(f"R2 へアップロード: {key}")
    s3.upload_file(
        str(ply_path),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Shibuya 3DGS batch")
    parser.add_argument("--force", action="store_true", help="枚数条件を無視")
    parser.add_argument("--dry-run", action="store_true", help="ダウンロード・学習せず判定だけ")
    parser.add_argument("--skip-train", action="store_true", help="ダウンロードまで（COLMAP/学習なし）")
    parser.add_argument("--prefix", default=None, help="R2 prefix 上書き")
    args = parser.parse_args()

    global FORCE, R2_PREFIX
    if args.force:
        FORCE = True
    if args.prefix:
        R2_PREFIX = args.prefix

    print("=" * 50)
    print("Shibuya Scramble 3DGS Batch")
    print(f"  bucket={R2_BUCKET}  prefix={R2_PREFIX}")
    print(f"  MIN={MIN_IMAGES}  MAX={MAX_IMAGES}  FORCE={FORCE}")
    print("=" * 50)

    s3 = get_s3_client()
    keys = list_photo_keys(s3, R2_PREFIX)
    info(f"R2 上の画像: {len(keys)} 枚")

    go, reason = decide_batch(keys)
    print(f"判定: {reason}")
    if not go:
        die("バッチを起動しません", code=0)

    if args.dry_run:
        ok("dry-run: ここで終了")
        return

    input_dir = DATA_DIR / "input"
    n = download_photos(s3, keys, input_dir)
    ok(f"{n} 枚を {input_dir} へ保存")

    if args.skip_train:
        ok("--skip-train: 学習をスキップ")
        return

    ensure_colmap()
    ensure_gaussian_splatting()
    ply = run_colmap_and_train(input_dir)

    if ply is None:
        die(".ply が生成されませんでした")

    ok(f"学習完了: {ply}")

    if UPLOAD_PLY:
        key = upload_ply(s3, ply)
        ok(f"R2 アップロード済: {key}")
    else:
        info("UPLOAD_PLY=0 のため R2 への送信をスキップ")

    ok("バッチ完了")


if __name__ == "__main__":
    main()
