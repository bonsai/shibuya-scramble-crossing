// docs/MODEL_SWITCHING.md
import * as THREE from 'three';

/**
 * Creates a procedural 3D model representing an abstract Shibuya Scramble Crossing.
 * Used as a zero-dependency fallback stage when no trained model is available.
 * @returns {THREE.Group}
 */
export function createPlaceholderCity() {
  const group = new THREE.Group();

  // Road surface (dark grey plane)
  const roadGeo = new THREE.PlaneGeometry(60, 60);
  const roadMat = new THREE.MeshStandardMaterial({ color: 0x222228, roughness: 0.8 });
  const road = new THREE.Mesh(roadGeo, roadMat);
  road.rotation.x = -Math.PI / 2;
  road.receiveShadow = true;
  group.add(road);

  // Crossing stripes (scramble intersection markings)
  const stripeMat = new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.5 });
  const angles = [0, Math.PI / 2, Math.PI / 4, -Math.PI / 4];
  
  angles.forEach((angle) => {
    const stripesGroup = new THREE.Group();
    stripesGroup.rotation.y = angle;
    for (let i = -5; i <= 5; i++) {
      const stripeGeo = new THREE.PlaneGeometry(1.2, 8);
      const stripe = new THREE.Mesh(stripeGeo, stripeMat);
      stripe.rotation.x = -Math.PI / 2;
      stripe.position.set(i * 2.2, 0.01, 15);
      stripesGroup.add(stripe);
    }
    group.add(stripesGroup);
  });

  // Building blocks (axis-aligned boxes around the junction)
  const buildingMat = new THREE.MeshStandardMaterial({ color: 0x3a3a4a, roughness: 0.4, metalness: 0.1 });

  const buildingsData = [
    { x: -22, z: -22, w: 12, h: 25, d: 12 },
    { x: 22, z: -22, w: 14, h: 35, d: 12 },
    { x: -22, z: 22, w: 12, h: 30, d: 12 },
    { x: 22, z: 22, w: 15, h: 20, d: 15 },
    { x: 0, z: -28, w: 20, h: 40, d: 10 },
    { x: 0, z: 28, w: 18, h: 28, d: 10 },
    { x: -28, z: 0, w: 10, h: 32, d: 18 },
    { x: 28, z: 0, w: 10, h: 22, d: 20 },
  ];

  buildingsData.forEach((b) => {
    const bGeo = new THREE.BoxGeometry(b.w, b.h, b.d);
    const mesh = new THREE.Mesh(bGeo, buildingMat);
    mesh.position.set(b.x, b.h / 2, b.z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  });

  return group;
}
