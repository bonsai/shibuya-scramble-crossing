// docs/MODEL_SWITCHING.md
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { loadGlbStage } from './stage-glb.js';
import { createPlaceholderCity } from './placeholder.js';

/**
 * Resolves the stage kind based on URL search parameters and device type.
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

export async function initViewer() {
  const canvas = document.getElementById('viewer-canvas');
  if (!canvas) return;

  const hudKind = document.getElementById('hud-kind');
  const hudSource = document.getElementById('hud-source');
  const hudAsset = document.getElementById('hud-asset');
  const hudStatus = document.getElementById('hud-status');

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

  // 4. Resolve Stage Kind
  const urlParams = new URLSearchParams(window.location.search);
  const isMobile = checkIsMobile();
  const kind = resolveKind(urlParams, isMobile);

  if (hudKind) hudKind.textContent = kind;

  let loadedStageObject = null;

  if (kind === 'city_gs') {
    // 3DGS path is not implemented in this skeleton
    if (hudStatus) hudStatus.textContent = '3DGS 未実装（プレースホルダーを表示中）';
    if (hudSource) hudSource.textContent = 'プレースホルダー (生成街)';
    if (hudAsset) hudAsset.textContent = '-';

    loadedStageObject = createPlaceholderCity();
    scene.add(loadedStageObject);
  } else {
    // city_glb path
    const stageResult = await loadGlbStage();
    loadedStageObject = stageResult.object;
    scene.add(loadedStageObject);

    if (hudSource) hudSource.textContent = stageResult.source;
    if (hudAsset) hudAsset.textContent = stageResult.assetKey || '-';
    if (hudStatus) hudStatus.textContent = stageResult.statusMsg;
  }

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
