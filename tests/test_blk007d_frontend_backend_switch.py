import json
import pathlib
import unittest

from backend.api.service import LoadingAPIService


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestBLK007DFrontendBackendSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.runtime = (ROOT / "frontend/src/backendSwitch.js").read_text(encoding="utf-8")
        cls.fixture = json.loads((ROOT / "frontend/mock/demo_loading_result.json").read_text())

    def test_default_path_has_no_local_solver_invocation(self):
        start = self.index.index("window.runSmartPackingAlgorithm = async")
        end = self.index.index("function showToast", start)
        default_path = self.index[start:end]
        self.assertNotIn("new IndustrialSmartContainerPacker", default_path)
        self.assertIn("window.BLK007D.calculate", default_path)
        self.assertIn("return;", default_path)

    def test_loading_result_base_endpoint(self):
        api = LoadingAPIService()
        api.put_result(self.fixture)
        status, result = api.dispatch("/api/v1/loading/demo_loading_job")
        self.assertEqual(status, 200)
        self.assertEqual(result["version"], "BLK007C")

    def test_missing_loading_job_is_404(self):
        status, result = LoadingAPIService().dispatch("/api/v1/loading/not-found")
        self.assertEqual(status, 404)
        self.assertEqual(result["error"], "LOADING_JOB_NOT_FOUND")

    def test_three_scene_is_loading_result_driven(self):
        self.assertIn("window.BLK007D.sceneObjects(loadingResult)", self.index)
        self.assertIn(".animation.frames", self.runtime)
        self.assertIn("loadingResult.camera", self.index)
        self.assertNotIn("generateBoxes()", self.index)

    def test_backend_configuration_and_explicit_mock(self):
        env = (ROOT / ".env").read_text()
        self.assertIn("VITE_LOADING_API_URL=", env)
        self.assertIn("query.get('mode') === 'mock'", self.runtime)
        self.assertIn("BackendStatus", self.runtime)

    def test_adapter_identity_consistency(self):
        cargo_ids = {item["id"] for item in self.fixture["cargo"]}
        scene_ids = {item["uuid"] for item in self.fixture["scene"]["objects"]}
        sequence_ids = {pid for step in self.fixture["sequence"]["steps"] for pid in step["placements"]}
        self.assertEqual(cargo_ids, scene_ids)
        self.assertTrue(sequence_ids <= scene_ids)

    def test_job_endpoint_uses_existing_search_profiles(self):
        server = (ROOT / "backend/server.py").read_text()
        self.assertIn("'/api/v1/loading/jobs'", server)
        self.assertIn("'MAX_COMPACT': SearchProfile.OPTIMIZE", server)
        self.assertNotIn("SearchProfile.MAX_COMPACT", server)


if __name__ == "__main__":
    unittest.main()
