// docs/MODEL_SWITCHING.md — Epic E+F issue #18 stage loading
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createPlaceholderCity } from './placeholder.js';

/**
 * Loads the mobile city GLB model or falls back to the procedural placeholder city.
 * 
 * @returns {Promise<{ object: THREE.Object3D, source: string, assetKey: string|null, statusMsg: string, dispose?: () => void }>}
 */
export async function loadGlbStage() {
  try {
    const latestRes = await fetch('/api/models/latest?kind=city_glb');
    if (!latestRes.ok) {
      throw new Error(`latest.json 取得失敗 (HTTP ${latestRes.status})`);
    }

    const latestData = await latestRes.json();
    if (!latestData || !latestData.asset) {
      throw new Error('アセットキーが見つかりません');
    }

    const assetKey = latestData.asset;
    const objectUrl = `/api/models/object?key=${encodeURIComponent(assetKey)}`;

    const loader = new GLTFLoader();
    const gltf = await new Promise((resolve, reject) => {
      loader.load(objectUrl, resolve, undefined, reject);
    });

    return {
      object: gltf.scene,
      source: 'GLB (学習済みモデル)',
      assetKey: assetKey,
      statusMsg: 'GLBモデルの読み込みに成功しました',
    };
  } catch (err) {
    console.warn('GLB stage load failed, falling back to placeholder city:', err);
    const placeholder = createPlaceholderCity();
    return {
      object: placeholder,
      source: 'プレースホルダー (生成街)',
      assetKey: null,
      statusMsg: `GLB非対応/未生成のためプレースホルダー表示 (${err.message || err})`,
    };
  }
}
