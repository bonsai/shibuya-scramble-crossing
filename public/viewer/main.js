// docs/MODEL_SWITCHING.md — Epic E+F issue #18 step2/step3 stage switching & dispatch
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { loadGlbStage } from './stage-glb.js';
import { loadSplatStage } from './stage-splat.js';

/**
 * Resolves the stage kind based on URL search parameters and device type.
 * Priority precedence: manual override parameter or URL searchParams `stage` (if valid city_gs | city_glb) > isMobile device check.
 * docs/MODEL_SWITCHING.md verbatim logic.
 *
 * @param {URLSearchParams|Object} searchParams
 * @param {boolean} isMobile
 * @returns {'city_gs'|'city_glb'}
 */
export function resolveKind(searchParams, isMobile) {
  const stage = typeof searchParams?.get === 'function'
    ? searchParams.get('stage')
    : searchParams?.stage;

  if (stage === 'city_gs' || stage === 'city_glb') {
    return stage;
  }
  if (isMobile) {
    return 'city_glb';
  }
  return 'city_gs';
}

/**
 * Checks if the current user agent or screen width represents a mobile device.
 * @returns {boolean}
 */
export function checkIsMobile() {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const isMobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  const isSmallScreen = typeof window !== 'undefined' && window.innerWidth <= 768;
  return isMobileUA || isSmallScreen;
}

/**
 * Recursively disposes GPU resources (geometries, materials, textures) from a Three.js object hierarchy.
 * @param {THREE.Object3D} object
 */
export function disposeObjectTree(object) {
  if (!object) return;

  object.traverse((child) => {
    if (child.geometry) {
      child.geometry.dispose();
    }
    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach((mat) => disposeMaterial(mat));
      } else {
        disposeMaterial(child.material);
      }
    }
  });
}

/**
 * Helper to dispose material and its attached textures.
 * @param {THREE.Material} material
 */
function disposeMaterial(material) {
  if (!material) return;
  Object.keys(material).forEach((prop) => {
    const val = material[prop];
    if (val && typeof val === 'object' && typeof val.dispose === 'function' && val.isTexture) {
      val.dispose();
    }
  });
  material.dispose();
}

export async function initViewer() {
  const canvas = document.getElementById('viewer-canvas');
  if (!canvas) return;

  const hudKind = document.getElementById('hud-kind');
  const hudSource = document.getElementById('hud-source');
  const hudAsset = document.getElementById('hud-asset');
  const hudStatus = document.getElementById('hud-status');
  const stageSelect = document.getElementById('stage-select');

  // 1. Setup Three.js Scene, Camera, Renderer
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0b0f);

  const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000
  );
  camera.position.set(0, 20, 40);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;

  // 2. Setup OrbitControls with clamped angles/distances
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.minDistance = 2;
  controls.maxDistance = 200;
  // Prevent camera from going below ground plane
  controls.maxPolarAngle = Math.PI / 2 - 0.01;

  // 3. Setup Lights
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
  dirLight.position.set(30, 50, 20);
  dirLight.castShadow = true;
  scene.add(dirLight);

  // Stage state tracking
  let currentStageObject = null;
  let currentStageDispose = null;
  let loadSessionId = 0;

  // Helper to load and mount stage
  // Precedence order: Manual UI Select (> 'auto') > URL override (`?stage=`) > Device auto-detection (`resolveKind`).
  async function switchStage(forcedKind) {
    const thisSession = ++loadSessionId;

    // Dispose old stage GPU resources cleanly
    if (currentStageObject) {
      scene.remove(currentStageObject);
      disposeObjectTree(currentStageObject);
      currentStageObject = null;
    }
    if (typeof currentStageDispose === 'function') {
      try {
        currentStageDispose();
      } catch (e) {
        console.warn('Error during stage disposal:', e);
      }
      currentStageDispose = null;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const isMobile = checkIsMobile();

    // Determine target kind based on precedence
    let targetKind;
    if (forcedKind === 'city_gs' || forcedKind === 'city_glb') {
      targetKind = forcedKind;
    } else {
      targetKind = resolveKind(urlParams, isMobile);
    }

    if (hudKind) hudKind.textContent = targetKind;
    if (hudSource) hudSource.textContent = 'ロード中…';
    if (hudAsset) hudAsset.textContent = '-';
    if (hudStatus) hudStatus.textContent = 'ステージ読み込み中…';

    let stageResult;
    if (targetKind === 'city_gs') {
      stageResult = await loadSplatStage(camera, renderer);
    } else {
      stageResult = await loadGlbStage();
    }

    // Ignore stale async completions if another stage switch occurred
    if (thisSession !== loadSessionId) {
      if (stageResult?.object) {
        disposeObjectTree(stageResult.object);
        if (typeof stageResult.dispose === 'function') stageResult.dispose();
      }
      return;
    }

    currentStageObject = stageResult.object;
    currentStageDispose = stageResult.dispose || null;
    scene.add(currentStageObject);

    if (hudSource) hudSource.textContent = stageResult.source;
    if (hudAsset) hudAsset.textContent = stageResult.assetKey || '-';
    if (hudStatus) hudStatus.textContent = stageResult.statusMsg;
  }

  // Bind HUD dropdown selector if present
  if (stageSelect) {
    const urlParams = new URLSearchParams(window.location.search);
    const urlStage = urlParams.get('stage');
    if (urlStage === 'city_gs' || urlStage === 'city_glb') {
      stageSelect.value = urlStage;
    } else {
      stageSelect.value = 'auto';
    }

    stageSelect.addEventListener('change', (e) => {
      const val = e.target.value;
      switchStage(val === 'auto' ? null : val);
    });
  }

  // Initial stage load
  await switchStage(null);

  // Handle window resizing
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // Animation loop
  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  animate();
}

// Auto-bootstrap when running in browser
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    initViewer().catch((err) => console.error('Viewer initialization failed:', err));
  });
}
