/**
 * sceneManager.js
 * Three.js Scene Management Module
 * - Scene/Camera/Renderer initialization
 * - Lighting and environment setup
 * - Container model building
 * - Door animations
 * - Adaptive cutaway system
 * - Viewport boundary enforcement
 * - Animation loop
 */

// ==================== Core Three.js Objects ====================
let scene, camera, renderer, controls;
let ambientLight, directionalLight, hemisphereLight, fillLight, rimLight;
let groundPlane, shadowPlane;

// Environment and materials
let envMap = null;
let envMapPath = '/assets/env/default_env.hdr';

// Container model groups
let containerWalls, containerFloorGroup, containerSkeletonGroup;
let frontLeftDoor, frontRightDoor;
let doorOpenProgress = 0;
let doorAnimating = false;

// Camera system
let cameraTransitioning = false;

// Cutaway and viewport
let adaptiveCutawayEnabled = false;
let foregroundOpacity = 1.0;

// Coordinate conversion constants
const V2_TO_THREE_SCALE = { x: 1, y: 1, z: 1 };
const V2_TO_THREE_OFFSET = { x: 0, y: 0, z: 0 };

// ==================== Initialization ====================

/**
 * Initialize Three.js scene, camera, renderer
 */
function init() {
  // Check Three.js availability
  if (typeof THREE === 'undefined') {
    console.error('[SceneManager] THREE is not defined. Retrying in 200ms...');
    setTimeout(startApp, 200);
    return;
  }

  // Scene
  scene = new THREE.Scene();
  scene.background = new THREE.Color(window.stateManager?.state?.sceneBackgroundColor || 0x0B0E14);

  // Camera (Orthographic)
  const aspect = window.innerWidth / window.innerHeight;
  const frustumSize = 15;
  camera = new THREE.OrthographicCamera(
    frustumSize * aspect / -2,
    frustumSize * aspect / 2,
    frustumSize / 2,
    frustumSize / -2,
    0.1,
    2000
  );
  camera.position.set(20, 15, 20);
  camera.lookAt(0, 0, 0);

  // Renderer
  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance'
  });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;

  const canvas = renderer.domElement;
  const container = document.getElementById('three-container');
  if (container) {
    container.innerHTML = '';
    container.appendChild(canvas);
  }

  // OrbitControls
  if (typeof THREE.OrbitControls !== 'undefined') {
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.085;
    controls.screenSpacePanning = true;
    controls.minZoom = 0.3;
    controls.maxZoom = 5.0;
    controls.enableRotate = true;
    controls.enablePan = true;
  } else {
    console.warn('[SceneManager] OrbitControls not available');
  }

  // Lighting
  setupLighting();

  // Environment
  setupEnvironment();

  // Ground plane
  const groundGeometry = new THREE.PlaneGeometry(100, 100);
  const groundMaterial = new THREE.ShadowMaterial({ opacity: 0.15 });
  groundPlane = new THREE.Mesh(groundGeometry, groundMaterial);
  groundPlane.rotation.x = -Math.PI / 2;
  groundPlane.position.y = -0.01;
  groundPlane.receiveShadow = true;
  scene.add(groundPlane);

  // Contact shadow plane
  const shadowGeometry = new THREE.PlaneGeometry(50, 50);
  const shadowMaterial = new THREE.ShadowMaterial({ opacity: 0.25 });
  shadowPlane = new THREE.Mesh(shadowGeometry, shadowMaterial);
  shadowPlane.rotation.x = -Math.PI / 2;
  shadowPlane.position.y = 0.001;
  shadowPlane.receiveShadow = true;
  scene.add(shadowPlane);

  // Mouse interaction
  canvas.addEventListener('mousemove', window.onMouseMove || function() {}, false);

  // Window resize
  window.addEventListener('resize', onWindowResize, false);

  console.log('[SceneManager] Initialization complete');
}

/**
 * Setup lighting system
 */
function setupLighting() {
  // Ambient light
  ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
  scene.add(ambientLight);

  // Directional light (sun)
  directionalLight = new THREE.DirectionalLight(0xffffff, 1.2);
  directionalLight.position.set(10, 20, 10);
  directionalLight.castShadow = true;
  directionalLight.shadow.mapSize.width = 2048;
  directionalLight.shadow.mapSize.height = 2048;
  directionalLight.shadow.camera.near = 0.5;
  directionalLight.shadow.camera.far = 100;
  directionalLight.shadow.camera.left = -30;
  directionalLight.shadow.camera.right = 30;
  directionalLight.shadow.camera.top = 30;
  directionalLight.shadow.camera.bottom = -30;
  directionalLight.shadow.radius = 2.0;
  scene.add(directionalLight);

  // Hemisphere light
  hemisphereLight = new THREE.HemisphereLight(0x87CEEB, 0x3E2723, 0.6);
  scene.add(hemisphereLight);

  // Fill light
  fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
  fillLight.position.set(-5, 5, -5);
  scene.add(fillLight);

  // Rim light
  rimLight = new THREE.DirectionalLight(0xffffff, 0.4);
  rimLight.position.set(0, 5, -10);
  scene.add(rimLight);
}

/**
 * Setup environment map
 */
function setupEnvironment() {
  if (typeof THREE.RGBELoader === 'undefined') {
    console.warn('[SceneManager] RGBELoader not available, skipping environment map');
    return;
  }

  const rgbeLoader = new THREE.RGBELoader();
  rgbeLoader.load(
    envMapPath,
    (texture) => {
      texture.mapping = THREE.EquirectangularReflectionMapping;
      envMap = texture;
      scene.environment = envMap;
      console.log('[SceneManager] Environment map loaded');
    },
    undefined,
    (err) => {
      console.warn('[SceneManager] Failed to load environment map:', err);
    }
  );
}

// ==================== Container Model ====================

/**
 * Rebuild container 3D model (walls, floor, doors, skeleton)
 */
function rebuildContainerModel() {
  const containerType = window.stateManager?.state?.containerType || '40HQ';
  const spec = window.stateManager?.getContainerSpec(containerType);
  if (!spec) {
    console.error('[SceneManager] Container spec not found for:', containerType);
    return;
  }

  const { innerLength, innerWidth, innerHeight } = spec.internal;

  // Clear existing container groups
  if (containerWalls) scene.remove(containerWalls);
  if (containerFloorGroup) scene.remove(containerFloorGroup);
  if (containerSkeletonGroup) scene.remove(containerSkeletonGroup);
  if (frontLeftDoor) scene.remove(frontLeftDoor);
  if (frontRightDoor) scene.remove(frontRightDoor);

  containerWalls = new THREE.Group();
  containerFloorGroup = new THREE.Group();
  containerSkeletonGroup = new THREE.Group();

  // Wall material
  const wallMaterial = new THREE.MeshStandardMaterial({
    color: 0xBBBBBB,
    metalness: 0.2,
    roughness: 0.8,
    side: THREE.DoubleSide
  });

  // Floor
  const floorGeometry = new THREE.BoxGeometry(innerLength, 0.05, innerWidth);
  const floorMesh = new THREE.Mesh(floorGeometry, wallMaterial.clone());
  floorMesh.position.set(innerLength / 2, -0.025, innerWidth / 2);
  floorMesh.castShadow = true;
  floorMesh.receiveShadow = true;
  containerFloorGroup.add(floorMesh);

  // Back wall (x = innerLength)
  const backWall = new THREE.Mesh(
    new THREE.BoxGeometry(0.05, innerHeight, innerWidth),
    wallMaterial.clone()
  );
  backWall.position.set(innerLength, innerHeight / 2, innerWidth / 2);
  backWall.castShadow = true;
  backWall.receiveShadow = true;
  containerWalls.add(backWall);

  // Left wall (z = 0)
  const leftWall = new THREE.Mesh(
    new THREE.BoxGeometry(innerLength, innerHeight, 0.05),
    wallMaterial.clone()
  );
  leftWall.position.set(innerLength / 2, innerHeight / 2, 0);
  leftWall.castShadow = true;
  leftWall.receiveShadow = true;
  containerWalls.add(leftWall);

  // Right wall (z = innerWidth)
  const rightWall = new THREE.Mesh(
    new THREE.BoxGeometry(innerLength, innerHeight, 0.05),
    wallMaterial.clone()
  );
  rightWall.position.set(innerLength / 2, innerHeight / 2, innerWidth);
  rightWall.castShadow = true;
  rightWall.receiveShadow = true;
  containerWalls.add(rightWall);

  // Top wall
  const topWall = new THREE.Mesh(
    new THREE.BoxGeometry(innerLength, 0.05, innerWidth),
    wallMaterial.clone()
  );
  topWall.position.set(innerLength / 2, innerHeight, innerWidth / 2);
  topWall.castShadow = true;
  topWall.receiveShadow = true;
  containerWalls.add(topWall);

  // Skeleton frame (edges)
  const edgesMaterial = new THREE.LineBasicMaterial({ color: 0x111827, linewidth: 2 });
  const skeletonGeometry = new THREE.BufferGeometry();
  const vertices = new Float32Array([
    // Bottom rectangle
    0, 0, 0,  innerLength, 0, 0,
    innerLength, 0, 0,  innerLength, 0, innerWidth,
    innerLength, 0, innerWidth,  0, 0, innerWidth,
    0, 0, innerWidth,  0, 0, 0,
    // Top rectangle
    0, innerHeight, 0,  innerLength, innerHeight, 0,
    innerLength, innerHeight, 0,  innerLength, innerHeight, innerWidth,
    innerLength, innerHeight, innerWidth,  0, innerHeight, innerWidth,
    0, innerHeight, innerWidth,  0, innerHeight, 0,
    // Vertical edges
    0, 0, 0,  0, innerHeight, 0,
    innerLength, 0, 0,  innerLength, innerHeight, 0,
    innerLength, 0, innerWidth,  innerLength, innerHeight, innerWidth,
    0, 0, innerWidth,  0, innerHeight, innerWidth
  ]);
  skeletonGeometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
  const skeletonLines = new THREE.LineSegments(skeletonGeometry, edgesMaterial);
  containerSkeletonGroup.add(skeletonLines);

  scene.add(containerWalls);
  scene.add(containerFloorGroup);
  scene.add(containerSkeletonGroup);

  // Build doors
  buildFrontDoors(innerWidth, innerHeight);

  console.log('[SceneManager] Container model rebuilt:', containerType);
}

/**
 * Build front doors (left and right)
 */
function buildFrontDoors(innerWidth, innerHeight) {
  const doorMaterial = new THREE.MeshStandardMaterial({
    color: 0x2E4057,
    metalness: 0.6,
    roughness: 0.4,
    side: THREE.DoubleSide
  });

  const doorWidth = innerWidth / 2;
  const doorThickness = 0.08;

  // Left door
  frontLeftDoor = new THREE.Group();
  const leftDoorPanel = new THREE.Mesh(
    new THREE.BoxGeometry(doorThickness, innerHeight, doorWidth),
    doorMaterial.clone()
  );
  leftDoorPanel.position.set(0, innerHeight / 2, doorWidth / 2);
  leftDoorPanel.castShadow = true;
  leftDoorPanel.receiveShadow = true;
  frontLeftDoor.add(leftDoorPanel);
  addHeavyDoorRod(frontLeftDoor, doorWidth, innerHeight, 'left');
  scene.add(frontLeftDoor);

  // Right door
  frontRightDoor = new THREE.Group();
  const rightDoorPanel = new THREE.Mesh(
    new THREE.BoxGeometry(doorThickness, innerHeight, doorWidth),
    doorMaterial.clone()
  );
  rightDoorPanel.position.set(0, innerHeight / 2, innerWidth - doorWidth / 2);
  rightDoorPanel.castShadow = true;
  rightDoorPanel.receiveShadow = true;
  frontRightDoor.add(rightDoorPanel);
  addHeavyDoorRod(frontRightDoor, doorWidth, innerHeight, 'right');
  scene.add(frontRightDoor);

  doorOpenProgress = 0;
}

/**
 * Add heavy door rod details
 */
function addHeavyDoorRod(doorGroup, doorWidth, doorHeight, side) {
  const rodMaterial = new THREE.MeshStandardMaterial({
    color: 0x1E293B,
    metalness: 0.9,
    roughness: 0.2
  });

  const rodRadius = 0.03;
  const rodLength = doorHeight * 0.8;

  // Vertical rod
  const rodGeometry = new THREE.CylinderGeometry(rodRadius, rodRadius, rodLength, 16);
  const rod = new THREE.Mesh(rodGeometry, rodMaterial);
  rod.position.set(0, doorHeight / 2, side === 'left' ? doorWidth - 0.15 : 0.15);
  rod.castShadow = true;
  doorGroup.add(rod);

  // Horizontal bars (3 pieces)
  for (let i = 0; i < 3; i++) {
    const barGeometry = new THREE.CylinderGeometry(rodRadius * 0.7, rodRadius * 0.7, doorWidth * 0.3, 12);
    const bar = new THREE.Mesh(barGeometry, rodMaterial);
    bar.rotation.z = Math.PI / 2;
    bar.position.set(0, doorHeight * (0.25 + i * 0.25), doorWidth / 2);
    bar.castShadow = true;
    doorGroup.add(bar);
  }
}

// ==================== Door Animation ====================

/**
 * Toggle door open/close animation
 */
window.toggleDoorAction = function() {
  if (doorAnimating) return;

  const targetProgress = doorOpenProgress > 0.5 ? 0 : 1;
  const duration = 1200;
  const startProgress = doorOpenProgress;
  const startTime = performance.now();

  doorAnimating = true;

  function animateDoor(time) {
    const elapsed = time - startTime;
    const t = Math.min(elapsed / duration, 1);

    // Quadratic easing
    const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    doorOpenProgress = startProgress + (targetProgress - startProgress) * eased;

    // Apply door rotation
    const maxAngle = Math.PI / 2;
    if (frontLeftDoor) {
      frontLeftDoor.rotation.y = -doorOpenProgress * maxAngle;
    }
    if (frontRightDoor) {
      frontRightDoor.rotation.y = doorOpenProgress * maxAngle;
    }

    if (t < 1) {
      requestAnimationFrame(animateDoor);
    } else {
      doorAnimating = false;
    }
  }

  requestAnimationFrame(animateDoor);
};

// ==================== Camera System ====================

/**
 * Switch camera to preset views with animation
 * @param {string} view - 'iso', 'front', 'side', 'top'
 */
window.switchCamera = function(view) {
  if (cameraTransitioning || !camera) return;

  const spec = window.stateManager?.getContainerSpec(window.stateManager?.state?.containerType || '40HQ');
  if (!spec) return;

  const { innerLength, innerWidth, innerHeight } = spec.internal;
  const centerX = innerLength / 2;
  const centerZ = innerWidth / 2;
  const centerY = innerHeight / 2;

  let targetPos;
  switch (view) {
    case 'iso':
      targetPos = { x: centerX + 20, y: centerY + 15, z: centerZ + 20 };
      break;
    case 'front':
      targetPos = { x: -20, y: centerY, z: centerZ };
      break;
    case 'side':
      targetPos = { x: centerX, y: centerY, z: centerZ + 20 };
      break;
    case 'top':
      targetPos = { x: centerX, y: 30, z: centerZ };
      break;
    default:
      return;
  }

  const startPos = { ...camera.position };
  const duration = 800;
  const startTime = performance.now();

  cameraTransitioning = true;

  function animateCamera(time) {
    const elapsed = time - startTime;
    const t = Math.min(elapsed / duration, 1);

    // Cubic easing
    const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

    camera.position.x = startPos.x + (targetPos.x - startPos.x) * eased;
    camera.position.y = startPos.y + (targetPos.y - startPos.y) * eased;
    camera.position.z = startPos.z + (targetPos.z - startPos.z) * eased;
    camera.lookAt(centerX, centerY, centerZ);

    if (t < 1) {
      requestAnimationFrame(animateCamera);
    } else {
      cameraTransitioning = false;
    }
  }

  requestAnimationFrame(animateCamera);
};

// ==================== Adaptive Cutaway System ====================

/**
 * Toggle adaptive cutaway system
 */
window.toggleAdaptiveCutaway = function() {
  adaptiveCutawayEnabled = !adaptiveCutawayEnabled;
  console.log('[SceneManager] Adaptive cutaway:', adaptiveCutawayEnabled ? 'ON' : 'OFF');

  if (!adaptiveCutawayEnabled) {
    // Restore all walls to opaque
    if (containerWalls) {
      containerWalls.children.forEach(wall => {
        if (wall.material) wall.material.opacity = 1.0;
      });
    }
  }
};

/**
 * Update cutaway opacity based on camera direction
 */
function updateAdaptiveCutaway() {
  if (!adaptiveCutawayEnabled || !camera || !containerWalls) return;

  const cameraDir = new THREE.Vector3();
  camera.getWorldDirection(cameraDir);
  cameraDir.normalize();

  const spec = window.stateManager?.getContainerSpec(window.stateManager?.state?.containerType || '40HQ');
  if (!spec) return;

  const { innerLength, innerWidth, innerHeight } = spec.internal;

  // Define wall face normals
  const walls = [
    { name: 'back', normal: new THREE.Vector3(1, 0, 0), index: 0 },
    { name: 'left', normal: new THREE.Vector3(0, 0, 1), index: 1 },
    { name: 'right', normal: new THREE.Vector3(0, 0, -1), index: 2 },
    { name: 'top', normal: new THREE.Vector3(0, 1, 0), index: 3 }
  ];

  walls.forEach(wall => {
    const dotProduct = cameraDir.dot(wall.normal);

    // If camera looks into the wall (dot > 0), make it transparent
    if (dotProduct > 0.3) {
      const opacity = Math.max(0.05, 1 - dotProduct);
      const mesh = containerWalls.children[wall.index];
      if (mesh && mesh.material) {
        mesh.material.transparent = true;
        mesh.material.opacity = opacity;
      }
    } else {
      const mesh = containerWalls.children[wall.index];
      if (mesh && mesh.material) {
        mesh.material.opacity = 1.0;
        mesh.material.transparent = false;
      }
    }
  });
}

// ==================== Viewport Boundary Enforcement ====================

/**
 * Enforce camera stays within viewport boundaries
 */
function enforceViewportBoundaries() {
  if (!camera || !controls) return;

  const spec = window.stateManager?.getContainerSpec(window.stateManager?.state?.containerType || '40HQ');
  if (!spec) return;

  const { innerLength, innerWidth, innerHeight } = spec.internal;

  const maxDistance = Math.max(innerLength, innerWidth, innerHeight) * 3;
  const center = new THREE.Vector3(innerLength / 2, innerHeight / 2, innerWidth / 2);
  const distance = camera.position.distanceTo(center);

  if (distance > maxDistance) {
    // Pull camera back toward center
    const direction = new THREE.Vector3().subVectors(center, camera.position).normalize();
    camera.position.addScaledVector(direction, (distance - maxDistance) * 0.1);
  }

  // Clamp Y position (don't go below floor)
  if (camera.position.y < 0.5) {
    camera.position.y = 0.5;
  }
}

// ==================== Window Resize ====================

function onWindowResize() {
  if (!camera || !renderer) return;

  const aspect = window.innerWidth / window.innerHeight;
  const frustumSize = 15;

  camera.left = frustumSize * aspect / -2;
  camera.right = frustumSize * aspect / 2;
  camera.top = frustumSize / 2;
  camera.bottom = frustumSize / -2;
  camera.updateProjectionMatrix();

  renderer.setSize(window.innerWidth, window.innerHeight);
}

// ==================== Animation Loop ====================

/**
 * Main render loop
 */
function animate() {
  requestAnimationFrame(animate);

  if (controls && controls.enabled) {
    controls.update();
  }

  // Update cutaway system
  updateAdaptiveCutaway();

  // Enforce viewport boundaries
  enforceViewportBoundaries();

  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}

// ==================== App Startup ====================

/**
 * Start the application
 */
function startApp() {
  console.log('[SceneManager] Starting application...');

  init();
  rebuildContainerModel();
  animate();

  console.log('[SceneManager] Application ready');
}

// Auto-start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}

// ==================== Window Exports ====================

window.sceneManager = {
  getScene: () => scene,
  getCamera: () => camera,
  getRenderer: () => renderer,
  getControls: () => controls,
  rebuildContainerModel,
  init,
  startApp
};

console.log('[SceneManager] Module loaded');