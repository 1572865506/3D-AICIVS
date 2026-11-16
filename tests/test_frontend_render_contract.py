"""前端 3D 渲染质量契约（静态回归闸门）。

只钉住“质感基础”不能被后续重构静默删掉的关键设置：
- 纸箱 albedo sRGB / anisotropy / 共享法线与 AO；
- PMREM 环境、静态阴影按需更新；
- 牛皮纸/彩色识别双模式、正交/透视双投影；
- 纸箱 receiveShadow 与 uv2。

这些是结构契约，不替代浏览器截图验收。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(PROJECT_ROOT, "index.html")
ORIENTATION = os.path.join(PROJECT_ROOT, "frontend", "src", "orientationRendering.js")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestRenderContract:
    def test_index_has_color_and_pbr_pipeline(self):
        src = _read(INDEX)
        for token in (
            "PMREMGenerator",
            "sRGBEncoding",
            "configureCargoAlbedoTexture",
            "getCardboardDetailMaps",
            "normalMap: detail.normalMap",
            "aoMap: detail.aoMap",
            "aoMapIntensity: 0.55",
            "roughness: ghost ? 0.90 : 0.84",
            "metalness: 0.0",
        ):
            assert token in src, f"缺少渲染契约: {token}"

    def test_index_has_shadow_and_palette_contract(self):
        src = _read(INDEX)
        for token in (
            "receiveShadow = true",
            "setShadowCasterState",
            "shadowMap.autoUpdate = false",
            "invalidateShadowMap",
            "packagePalette",
            "setPackagePalette",
            "btn-palette-kraft",
            "btn-palette-color",
            "cargoReceiveShadow",
            "setCargoReceiveShadow",
            "btn-cargo-shadow-off",
            "cargoCastShadow",
            "setCargoCastShadow",
            "btn-cargo-cast-off",
        ):
            assert token in src, f"缺少渲染契约: {token}"

    def test_index_has_dual_camera_contract(self):
        src = _read(INDEX)
        for token in (
            "PerspectiveCamera",
            "setCameraProjection",
            "btn-proj-ortho",
            "btn-proj-perspective",
            "getPerspectiveDistance",
            "ensureStudioBackdrop",
        ):
            assert token in src, f"缺少渲染契约: {token}"

    def test_cargo_geometry_exposes_uv2_and_shared_flag(self):
        src = _read(ORIENTATION)
        assert "setAttribute('uv2'" in src
        assert "geometry.userData.shared = true" in src

    def test_packing_demo_contract(self):
        src = _read(INDEX)
        for token in (
            "packingAnimation.js",
            "animation-hud",
            "btn-anim-pause",
            "btn-anim-stop",
            "btn-anim-skip",
            "btn-anim-follow",
            "togglePackingAnimationPause",
            "setPackingAnimationSpeed",
            "togglePackingAnimationFollow",
            "cancelPackingAnimation",
            "getPackingAnimationState",
            "prefers-reduced-motion",
            "__packingAnimationActive",
        ):
            assert token in src, f"缺少装柜演示契约: {token}"

    def test_user_requested_default_render_values(self):
        src = _read(INDEX)
        for token in (
            "frameMetal: 0.88",
            "frameRough: 0.58",
            "bump: 0.60",
            "ambIntensity: 0.30",
            "shadowRadius: 1.5",
            "groundShadowOpacity: 0",
            "contactShadowOpacity: 0.45",
            "fill2Intensity: 0",
            "fill1Intensity: 0.35",
            "hemiIntensity: 0.45",
            "cargoCastShadow: false",
            "cargoReceiveShadow: false",
        ):
            assert token in src, f"默认渲染值漂移: {token}"
