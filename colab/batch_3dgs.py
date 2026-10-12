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
        "export_latest": True,
        "export_placements": True,
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
    if (v := env_bool("EXPORT_LATEST")) is not None:
        wf["export_latest"] = v
    elif (v := env_bool("UPDATE_LATEST")) is not None:
        wf["export_latest"] = v
    if (v := env_bool("EXPORT_PLACEMENTS")) is not None:
        wf["export_placements"] = v
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
    import json

    dest_dir.mkdir(parents=True, exist_ok=True)
    for p in dest_dir.glob("*"):
        if p.is_file():
            p.unlink()

    selected = keys[:max_images]
    key_map: dict[str, str] = {}
    for i, key in enumerate(selected, 1):
        ext = Path(key).suffix.lower() or ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"
        local_name = f"{i:04d}{ext}"
        dest = dest_dir / local_name
        s3.download_file(bucket, key, str(dest))
        key_map[local_name] = key
        if i % 20 == 0 or i == len(selected):
            print(f"  download {i}/{len(selected)}")

    map_path = dest_dir / "r2_key_map.json"
    with map_path.open("w", encoding="utf-8") as f:
        json.dump(key_map, f, indent=2, ensure_ascii=False)
    if dest_dir.parent != dest_dir:
        parent_map_path = dest_dir.parent / "r2_key_map.json"
        with parent_map_path.open("w", encoding="utf-8") as f:
            json.dump(key_map, f, indent=2, ensure_ascii=False)

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


def upload_latest_json(s3, bucket: str, ply_r2_key: str, iterations: int) -> str:
    import json

    data = {
        "version": 1,
        "kind": "city_gs",
        "asset": ply_r2_key,
        "format": "ply",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "iterations": iterations,
    }
    key = "models/city_gs/latest.json"
    info(f"R2 へ latest.json をアップロード: {key}")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return key


# We emit a CAMERA-TO-WORLD quaternion [qw,qx,qy,qz] (i.e. the inverse of COLMAP's stored world-to-camera rotation).
def colmap_to_c2w(
    qw: float, qx: float, qy: float, qz: float, tx: float, ty: float, tz: float
) -> tuple[list[float], list[float]]:
    import math

    norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    if norm > 0:
        qw, qx, qy, qz = qw / norm, qx / norm, qy / norm, qz / norm

    # Rotation matrix R_w2c from quaternion q_w2c
    r11 = 1.0 - 2.0 * (qy * qy + qz * qz)
    r12 = 2.0 * (qx * qy - qz * qw)
    r13 = 2.0 * (qx * qz + qy * qw)

    r21 = 2.0 * (qx * qy + qz * qw)
    r22 = 1.0 - 2.0 * (qx * qx + qz * qz)
    r23 = 2.0 * (qy * qz - qx * qw)

    r31 = 2.0 * (qx * qz - qy * qw)
    r32 = 2.0 * (qy * qz + qx * qw)
    r33 = 1.0 - 2.0 * (qx * qx + qy * qy)

    # R_c2w = R_w2c^T
    # Position C = - R_c2w * t
    cx = -(r11 * tx + r21 * ty + r31 * tz)
    cy = -(r12 * tx + r22 * ty + r32 * tz)
    cz = -(r13 * tx + r23 * ty + r33 * tz)

    # Quaternion for R_c2w is q_w2c conjugate: [qw, -qx, -qy, -qz]
    qw_c2w = qw
    qx_c2w = -qx
    qy_c2w = -qy
    qz_c2w = -qz

    return [float(cx), float(cy), float(cz)], [
        float(qw_c2w),
        float(qx_c2w),
        float(qy_c2w),
        float(qz_c2w),
    ]


def parse_colmap_cameras_text(cameras_file: Path) -> dict[int, float | None]:
    import math

    cameras_fov: dict[int, float | None] = {}
    with cameras_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            camera_id = int(parts[0])
            model = parts[1].upper()
            width = float(parts[2])
            height = float(parts[3])
            params = [float(p) for p in parts[4:]]

            fov = None
            if model in (
                "SIMPLE_PINHOLE",
                "SIMPLE_RADIAL",
                "RADIAL",
                "SIMPLE_RADIAL_FISHEYE",
                "RADIAL_FISHEYE",
            ):
                if len(params) >= 1 and params[0] > 0:
                    fov = math.degrees(2.0 * math.atan(width / (2.0 * params[0])))
            elif model in (
                "PINHOLE",
                "OPENCV",
                "OPENCV_FISHEYE",
                "FOV",
                "THIN_PRISM_FISHEYE",
            ):
                if len(params) >= 1 and params[0] > 0:
                    fov = math.degrees(2.0 * math.atan(width / (2.0 * params[0])))
            cameras_fov[camera_id] = round(fov, 4) if fov is not None else None
    return cameras_fov


def parse_colmap_images_text(images_file: Path) -> list[dict]:
    images = []
    expect_header = True
    with images_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if expect_header:
                parts = line.split()
                if len(parts) >= 10:
                    image_id = int(parts[0])
                    qw, qx, qy, qz = (
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                        float(parts[4]),
                    )
                    tx, ty, tz = (
                        float(parts[5]),
                        float(parts[6]),
                        float(parts[7]),
                    )
                    camera_id = int(parts[8])
                    name = " ".join(parts[9:])
                    images.append(
                        {
                            "image_id": image_id,
                            "qw": qw,
                            "qx": qx,
                            "qy": qy,
                            "qz": qz,
                            "tx": tx,
                            "ty": ty,
                            "tz": tz,
                            "camera_id": camera_id,
                            "name": name,
                        }
                    )
                expect_header = False
            else:
                expect_header = True
    return images


# Fallback to binary parse if no text model exists
def parse_colmap_cameras_binary(cameras_file: Path) -> dict[int, float | None]:
    import math
    import struct

    MODEL_NUM_PARAMS = {
        0: 3,
        1: 4,
        2: 4,
        3: 5,
        4: 8,
        5: 8,
        6: 12,
        7: 5,
        8: 4,
        9: 5,
        10: 12,
    }
    cameras_fov: dict[int, float | None] = {}
    with cameras_file.open("rb") as f:
        num_cameras = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_cameras):
            camera_id, model_id, width, height = struct.unpack(
                "<iiQQ", f.read(24)
            )
            num_params = MODEL_NUM_PARAMS.get(model_id, 0)
            params = struct.unpack(f"<{num_params}d", f.read(8 * num_params))
            fov = None
            if model_id in (0, 2, 3, 8, 9):
                if len(params) >= 1 and params[0] > 0:
                    fov = math.degrees(2.0 * math.atan(width / (2.0 * params[0])))
            elif model_id in (1, 4, 5, 7, 10):
                if len(params) >= 1 and params[0] > 0:
                    fov = math.degrees(2.0 * math.atan(width / (2.0 * params[0])))
            cameras_fov[camera_id] = round(fov, 4) if fov is not None else None
    return cameras_fov


def parse_colmap_images_binary(images_file: Path) -> list[dict]:
    import struct

    images = []
    with images_file.open("rb") as f:
        num_images = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_images):
            image_id, qw, qx, qy, qz, tx, ty, tz, camera_id = struct.unpack(
                "<IddddddddI", f.read(64)
            )
            name_bytes = bytearray()
            while True:
                b = f.read(1)
                if not b or b == b"\x00":
                    break
                name_bytes.extend(b)
            name = name_bytes.decode("utf-8", errors="replace")
            num_p2d = struct.unpack("<Q", f.read(8))[0]
            f.seek(num_p2d * 24, 1)
            images.append(
                {
                    "image_id": image_id,
                    "qw": qw,
                    "qx": qx,
                    "qy": qy,
                    "qz": qz,
                    "tx": tx,
                    "ty": ty,
                    "tz": tz,
                    "camera_id": camera_id,
                    "name": name,
                }
            )
    return images


def export_placements(
    s3, bucket: str, data_dir: Path, gs_repo: Path, ply_key: str | None
) -> None:
    import json

    data_root = gs_repo / "data"
    sparse_dir = None
    for candidate in [
        data_root / "sparse" / "0",
        data_root / "sparse",
    ]:
        if (candidate / "images.txt").exists() or (candidate / "images.bin").exists():
            sparse_dir = candidate
            break

    if sparse_dir is None:
        for p in data_root.rglob("images.txt"):
            sparse_dir = p.parent
            break
        if sparse_dir is None:
            for p in data_root.rglob("images.bin"):
                sparse_dir = p.parent
                break

    if sparse_dir is None:
        info("COLMAP の sparse モデルが見つかりません。placements エクスポートをスキップします。")
        return

    try:
        if (sparse_dir / "images.txt").exists() and (sparse_dir / "cameras.txt").exists():
            info(f"COLMAP テキストモデルを読み込み中: {sparse_dir}")
            cameras_fov = parse_colmap_cameras_text(sparse_dir / "cameras.txt")
            raw_images = parse_colmap_images_text(sparse_dir / "images.txt")
        elif (sparse_dir / "images.bin").exists() and (sparse_dir / "cameras.bin").exists():
            info(f"COLMAP バイナリモデルを読み込み中 (テキストモデル未検出): {sparse_dir}")
            cameras_fov = parse_colmap_cameras_binary(sparse_dir / "cameras.bin")
            raw_images = parse_colmap_images_binary(sparse_dir / "images.bin")
        else:
            info(f"COLMAP sparse モデルファイルが不足しています ({sparse_dir})。placements エクスポートをスキップします。")
            return
    except Exception as e:
        info(f"COLMAP sparse モデルの解析に失敗しました ({e})。placements エクスポートをスキップします。")
        return

    key_map = {}
    for map_file in [data_dir / "r2_key_map.json", data_dir / "input" / "r2_key_map.json"]:
        if map_file.exists():
            try:
                with map_file.open("r", encoding="utf-8") as f:
                    key_map = json.load(f)
                break
            except Exception:
                pass

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    placements = []

    for img in raw_images:
        local_name = Path(img["name"]).name
        photo_key = key_map.get(local_name)
        pos, rot = colmap_to_c2w(
            img["qw"], img["qx"], img["qy"], img["qz"],
            img["tx"], img["ty"], img["tz"]
        )
        fov = cameras_fov.get(img["camera_id"])
        placements.append(
            {
                "id": Path(local_name).stem,
                "photo_key": photo_key,
                "local_name": local_name,
                "position": pos,
                "rotation": rot,
                "fov_deg": fov,
                "source": "colmap",
                "created_at": created_at,
            }
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_key = f"placements/{ts}.json"
    info(f"R2 へ placements をアップロード: {export_key} ({len(placements)} 件)")
    s3.put_object(
        Bucket=bucket,
        Key=export_key,
        Body=json.dumps(placements, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )

    index_data = {
        "version": 1,
        "updated_at": created_at,
        "export_key": export_key,
        "count": len(placements),
        "source": "colmap",
        "model_ref": ply_key,
        "transform": None,
    }
    index_key = "placements/index.json"
    info(f"R2 へ placements/index.json を更新: {index_key}")
    s3.put_object(
        Bucket=bucket,
        Key=index_key,
        Body=json.dumps(index_data, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


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
    export_latest_flag = bool(wf.get("export_latest", True))
    export_placements_flag = bool(wf.get("export_placements", True))
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

    ply_key = None
    if upload_ply_flag:
        ply_key = upload_ply(s3, bucket, ply, ply_prefix)
        ok(f"R2 アップロード済: {ply_key}")
        if export_latest_flag:
            latest_key = upload_latest_json(s3, bucket, ply_key, iterations)
            ok(f"R2 latest.json 更新済: {latest_key}")
        else:
            info("export_latest=false のため latest.json の更新をスキップ")
    else:
        info("upload_ply=false のため R2 への送信をスキップ")

    if export_placements_flag:
        export_placements(s3, bucket, data_dir, gs_repo, ply_key)
    else:
        info("export_placements=false のため placements のエクスポートをスキップ")

    ok("バッチ完了")


if __name__ == "__main__":
    main()
