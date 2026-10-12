// docs/MODEL_SWITCHING.md — Epic E+F issue #18 step2 desktop 3DGS stage
import * as THREE from 'three';
import { DropInViewer, SceneFormat } from '@mkkellogg/gaussian-splats-3d';
import { createPlaceholderCity } from './placeholder.js';

/**
 * Maps asset format string to SceneFormat enum expected by @mkkellogg/gaussian-splats-3d.
 *
 * @param {string} format
 * @returns {number|null}
 */
function resolveSceneFormat(format) {
  if (!format) return null;
  const fmt = String(format).toLowerCase();
  if (fmt === 'ply') return SceneFormat.Ply;
  if (fmt === 'splat') return SceneFormat.Splat;
  if (fmt === 'ksplat') return SceneFormat.KSplat;
  return null;
}

/**
 * Loads the 3D Gaussian Splatting stage or falls back to the procedural placeholder city.
 * Mirroring the export shape of stage-glb.js.
 *
 * @param {THREE.Camera} [camera]
 * @param {THREE.WebGLRenderer} [renderer]
 * @returns {Promise<{ object: THREE.Object3D, source: string, assetKey: string|null, statusMsg: string, dispose?: () => void }>}
 */
export async function loadSplatStage(camera, renderer) {
  try {
    const latestRes = await fetch('/api/models/latest?kind=city_gs');
    if (!latestRes.ok) {
      throw new Error(`latest.json 取得失敗 (HTTP ${latestRes.status})`);
    }

    const latestData = await latestRes.json();
    if (!latestData || !latestData.asset) {
      throw new Error('アセットキーが見つかりません');
    }

    const assetKey = latestData.asset;
    const format = latestData.format || 'ply';
    const sceneFormat = resolveSceneFormat(format);

    if (sceneFormat === null) {
      throw new Error(`未対応のフォーマットです: ${format}`);
    }

    const objectUrl = `/api/models/object?key=${encodeURIComponent(assetKey)}`;

    const dropInViewer = new DropInViewer({
      camera,
      renderer,
      sharedMemoryForWorkers: false,
      gpuAcceleratedSort: false,
    });

    await dropInViewer.addSplatScene(objectUrl, {
      format: sceneFormat,
      showLoadingUI: false,
      progressiveLoad: false,
    });

    return {
      object: dropInViewer,
      source: `3DGS (学習済みモデル: ${format.toUpperCase()})`,
      assetKey: assetKey,
      statusMsg: '3DGSモデルの読み込みに成功しました',
      dispose: () => {
        try {
          dropInViewer.dispose();
        } catch (e) {
          console.warn('DropInViewer dispose error:', e);
        }
      },
    };
  } catch (err) {
    console.warn('3DGS stage load failed, falling back to placeholder city:', err);
    const placeholder = createPlaceholderCity();
    return {
      object: placeholder,
      source: 'プレースホルダー (生成街)',
      assetKey: null,
      statusMsg: `3DGS非対応/未生成のためプレースホルダー表示 (${err.message || err})`,
    };
  }
}
