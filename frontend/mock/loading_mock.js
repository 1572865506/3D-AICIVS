/* BLK-007C offline Three.js adapter. API scene coordinates are already authoritative. */
export async function loadDemo(url = './demo_loading_result.json') {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Loading mock failed: ${response.status}`);
  return response.json();
}

export function createThreeScene(THREE, loadingResult) {
  const root = new THREE.Group();
  root.name = loadingResult.id;
  for (const object of loadingResult.scene.objects) {
    const geometry = new THREE.BoxGeometry(...object.scale);
    const material = new THREE.MeshStandardMaterial({
      color: object.style.color,
      transparent: object.style.opacity < 1,
      opacity: object.style.opacity,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = object.uuid;
    mesh.position.set(...object.position);
    mesh.rotation.set(...object.rotation);
    mesh.userData = object.metadata;
    root.add(mesh);
  }
  return root;
}

export async function playLoading(root, loadingResult, onFrame, delayMs = 250) {
  for (const child of root.children) child.visible = false;
  for (const frame of loadingResult.animation.frames) {
    for (const id of frame.objects) {
      const object = root.getObjectByName(id);
      if (object) object.visible = true;
    }
    if (onFrame) onFrame(frame);
    await new Promise(resolve => setTimeout(resolve, delayMs));
  }
}
