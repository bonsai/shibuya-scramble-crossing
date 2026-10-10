#!/usr/bin/env python3
"""
Shibuya Scramble Crossing — 3DGS バッチ自動化スクリプト

用途:
  - R2 の写真数を確認し、条件を満たすとダウンロード
  - COLMAP + gaussian-splatting で学習（Colab / Kaggle 向け）
  - 完了後の .ply を R2 に戻すオプションあり

設定の優先順位:
  CLI引数 > 環境変数 > YAML (batch_config.yaml) > デフォルト

使い方（Colab）:
  !python batch_3dgs.py --config /content/batch_config.yaml

必須環境変数（YAML に書かない）:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------- デフォルト ----------

DEFAULTS: dict[str, Any] = {
    "r2": {
        "bucket": "shibuya-scramble",
        "prefix": "photos/",
    },
    "thresholds": {
        "min_images": 80,
        "max_images": 150,
    },
    "workflow": {
        "force": False,
        "dry_run": False,
        "skip_train": False,
        "upload_ply": True,
        "iterations": 15000,
        "save_iterations": [7000, 15000],
    },
    "paths": {
        "data_dir": "/content/data",
        "output_dir": "/content/output",
        "gs_repo": "/content/gaussian-splatting",
        "ply_r2_prefix": "models/city_gs/",
    },
    "images": {
        "extensions": [".jpg", ".jpeg", ".png", ".webp"],
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyyaml"])
        import yaml

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def env_int(key: str) -> int | None:
    v = env(key)
    return int(v) if v else None


def env_bool(key: str) -> bool | None:
    v = env(key).lower()
    if not v:
        return None
    return v in ("1", "true", "yes", "on")


def apply_env_overrides(cfg: dict) -> dict:
    """環境変数で YAML を上書き。"""
    r2 = cfg.setdefault("r2", {})
    th = cfg.setdefault("thresholds", {})
    wf = cfg.setdefault("workflow", {})
    paths = cfg.setdefault("paths", {})

    if env("R2_BUCKET"):
        r2["bucket"] = env("R2_BUCKET")
    if env("R2_PREFIX"):
        r2["prefix"] = env("R2_PREFIX")

    if (v := env_int("MIN_IMAGES")) is not None:
        th["min_images"] = v
    if (v := env_int("MAX_IMAGES")) is not None:
        th["max_images"] = v

    if (v := env_bool("FORCE")) is not None:
        wf["force"] = v
    if (v := env_bool("UPLOAD_PLY")) is not None:
        wf["upload_ply"] = v
    if (v := env_int("ITERATIONS")) is not None:
        wf["iterations"] = v

    if env("DATA_DIR"):
        paths["data_dir"] = env("DATA_DIR")
    if env("OUTPUT_DIR"):
        paths["output_dir"] = env("OUTPUT_DIR")

    return cfg


def build_config(config_path: Path | None) -> dict:
    cfg = dict(DEFAULTS)
    if config_path and config_path.is_file():
        yaml_cfg = load_yaml(config_path)
        cfg = deep_merge(cfg, yaml_cfg)
        print(f"ℹ️  loaded config: {config_path}")
    elif config_path:
        print(f"⚠️  config not found, using defaults: {config_path}")
    cfg = apply_env_overrides(cfg)
    return cfg


# ---------- ログ ----------

def die(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"ℹ️  {msg}")


def ok(msg: str) -> None:
    print(f"✅ {msg}")


# ---------- R2 ----------

def get_s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "boto3"])
        import boto3
        from botocore.config import Config

    account = env("R2_ACCOUNT_ID")
    access = env("R2_ACCESS_KEY_ID")
    secret = env("R2_SECRET_ACCESS_KEY")
    if not all([account, access, secret]):
        die("R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY を設定してください")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def list_photo_keys(s3, bucket: str, prefix: str, extensions: list[str]) -> list[str]:
    keys: list[str] = []
    continuation = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            k = obj["Key"]
            if k.lower().endswith(tuple(extensions)):
                keys.append(k)
        if not resp.get("IsTruncated"):
            break
        continuation = resp.get("NextContinuationToken")
    return keys


def decide_batch(n: int, min_images: int, force: bool) -> tuple[bool, str]:
    if force:
        return True, f"force=true のため実行 (n={n})"
    if n < min_images:
        return False, f"写真数不足: {n} < min_images={min_images}"
    return True, f"条件達成: {n} 枚 >= {min_images}"


def download_photos(
    s3, bucket: str, keys: list[str], dest_dir: Path, max_images: int
) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for p in dest_dir.glob("*"):
        if p.is_file():
            p.unlink()

    selected = keys[:max_images]
    for i, key in enumerate(selected, 1):
        ext = Path(key).suffix.lower() or ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"
        dest = dest_dir / f"{i:04d}{ext}"
        s3.download_file(bucket, key, str(dest))
        if i % 20 == 0 or i == len(selected):
            print(f"  download {i}/{len(selected)}")
    return len(selected)


def ensure_gaussian_splatting(gs_repo: Path) -> None:
    if gs_repo.exists() and (gs_repo / "train.py").exists():
        info("gaussian-splatting 既にあり")
        return
    info("gaussian-splatting を clone...")
    subprocess.check_call(
        [
            "git",
            "clone",
            "--recursive",
            "-q",
            "https://github.com/graphdeco-inria/gaussian-splatting",
            str(gs_repo),
        ]
    )
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "submodules/diff-gaussian-rasterization"],
        cwd=gs_repo,
    )
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "submodules/simple-knn"],
        cwd=gs_repo,
    )


def ensure_colmap() -> None:
    try:
        subprocess.check_call(
            ["colmap", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    info("COLMAP をインストール...")
    subprocess.check_call(["apt-get", "-qq", "update"])
    subprocess.check_call(
        ["apt-get", "-qq", "install", "-y", "colmap"], stdout=subprocess.DEVNULL
    )


def run_colmap_and_train(
    input_dir: Path,
    gs_repo: Path,
    output_dir: Path,
    iterations: int,
    save_iterations: list[int],
) -> Path | None:
    data_root = gs_repo / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    link = data_root / "input"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(input_dir)

    info("COLMAP (convert.py)...")
    subprocess.check_call(
        [sys.executable, "convert.py", "-s", str(data_root)],
        cwd=gs_repo,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    save_args = [str(x) for x in save_iterations]
    info(f"train.py (iterations={iterations})...")
    cmd = [
        sys.executable,
        "train.py",
        "-s",
        str(data_root),
        "-m",
        str(output_dir),
        "--iterations",
        str(iterations),
        "--save_iterations",
        *save_args,
    ]
    subprocess.check_call(cmd, cwd=gs_repo)

    plys = sorted(output_dir.rglob("*.ply"))
    if not plys:
        return None
    return plys[-1]


def upload_ply(s3, bucket: str, ply_path: Path, ply_prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"{ply_prefix.rstrip('/')}/{ts}_{ply_path.name}"
    info(f"R2 へアップロード: {key}")
    s3.upload_file(
        str(ply_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Shibuya 3DGS batch")
    parser.add_argument(
        "--config",
        "-c",
        default="batch_config.yaml",
        help="YAML config path (default: batch_config.yaml)",
    )
    parser.add_argument("--force", action="store_true", help="枚数条件を無視")
    parser.add_argument("--dry-run", action="store_true", help="判定だけ")
    parser.add_argument("--skip-train", action="store_true", help="ダウンロードまで")
    parser.add_argument("--prefix", default=None, help="R2 prefix 上書き")
    args = parser.parse_args()

    cfg = build_config(Path(args.config))

    r2 = cfg["r2"]
    th = cfg["thresholds"]
    wf = cfg["workflow"]
    paths = cfg["paths"]
    exts = cfg["images"]["extensions"]

    # CLI が最優先
    if args.force:
        wf["force"] = True
    if args.dry_run:
        wf["dry_run"] = True
    if args.skip_train:
        wf["skip_train"] = True
    if args.prefix:
        r2["prefix"] = args.prefix

    bucket = r2["bucket"]
    prefix = r2["prefix"]
    min_images = int(th["min_images"])
    max_images = int(th["max_images"])
    force = bool(wf["force"])
    dry_run = bool(wf["dry_run"])
    skip_train = bool(wf["skip_train"])
    upload_ply_flag = bool(wf["upload_ply"])
    iterations = int(wf["iterations"])
    save_iterations = list(wf.get("save_iterations") or [7000, iterations])
    data_dir = Path(paths["data_dir"])
    output_dir = Path(paths["output_dir"])
    gs_repo = Path(paths["gs_repo"])
    ply_prefix = paths.get("ply_r2_prefix", "models/city_gs/")

    print("=" * 50)
    print("Shibuya Scramble 3DGS Batch")
    print(f"  bucket={bucket}  prefix={prefix}")
    print(f"  min={min_images}  max={max_images}  force={force}")
    print(f"  iterations={iterations}  upload_ply={upload_ply_flag}")
    print("=" * 50)

    s3 = get_s3_client()
    keys = list_photo_keys(s3, bucket, prefix, exts)
    info(f"R2 上の画像: {len(keys)} 枚")

    go, reason = decide_batch(len(keys), min_images, force)
    print(f"判定: {reason}")
    if not go:
        die("バッチを起動しません", code=0)

    if dry_run:
        ok("dry-run: ここで終了")
        return

    input_dir = data_dir / "input"
    n = download_photos(s3, bucket, keys, input_dir, max_images)
    ok(f"{n} 枚を {input_dir} へ保存")

    if skip_train:
        ok("skip_train: 学習をスキップ")
        return

    ensure_colmap()
    ensure_gaussian_splatting(gs_repo)
    ply = run_colmap_and_train(
        input_dir, gs_repo, output_dir, iterations, save_iterations
    )

    if ply is None:
        die(".ply が生成されませんでした")

    ok(f"学習完了: {ply}")

    if upload_ply_flag:
        key = upload_ply(s3, bucket, ply, ply_prefix)
        ok(f"R2 アップロード済: {key}")
    else:
        info("upload_ply=false のため R2 への送信をスキップ")

    ok("バッチ完了")


if __name__ == "__main__":
    main()
