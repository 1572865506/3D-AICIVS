"""自学习模块测试：特征、k-NN、训练门槛、影子选择器与安全回退。

钉住四件事：
1. 特征抽取稳定且全部有限；
2. 策略档 → 产品门区选项映射正确（与 server/验收共用）；
3. 训练门槛：样本不足/单一标签/准确率不够时 enabled=False；
4. 选择器永远有回退路径，且"封门薄板/易碎"场景不允许建议装载率优先。

被谁调用：pytest 测试收集器。
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.evaluation.product import build_product_options
from backend.solver_v2.evaluation.scenarios import detect_scenario
from backend.solver_v2.evaluation.spec import get_policy
from backend.solver_v2.learning.features import FEATURE_NAMES, extract_features, to_vector
from backend.solver_v2.learning.model import fit, leave_one_out, predict
from backend.solver_v2.learning.selector import suggest_policy
from backend.solver_v2.learning.train import train

FIXTURE = os.path.join(PROJECT_ROOT, "tests", "fixtures", "production_15sku.json")


def _setup():
    case = json.load(open(FIXTURE, encoding="utf-8"))
    return InputAdapter.parse_container(case["container"]), InputAdapter.parse_cargo_list(case["cargo"])


def _mini_cargo():
    case = {
        "container": {"usable": {"L": 4.0, "W": 2.35, "H": 2.69}},
        "cargo": [
            {"sku": "A", "name": "A", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 5, "quantity": 20, "requirement": "放中间"},
        ],
    }
    return InputAdapter.parse_container(case["container"]), InputAdapter.parse_cargo_list(case["cargo"])


class TestFeatures:
    def test_feature_vector_is_complete_and_finite(self):
        container, cargo = _setup()
        feats = extract_features(cargo, container)
        assert set(feats) == set(FEATURE_NAMES)
        vector = to_vector(feats)
        assert len(vector) == len(FEATURE_NAMES)
        assert all(isinstance(v, float) and v == v for v in vector)
        assert feats["has_rigid_door"] == 1.0
        assert feats["has_thin_panel"] == 1.0


class TestProductPolicyOptions:
    def test_policy_mapping(self):
        container, cargo = _setup()
        safety = build_product_options(cargo, policy="SAFETY_FIRST")
        assert safety["door_seal_confine"] is True
        assert safety["door_step_depth"] == pytest.approx(0.25)

        balanced = build_product_options(cargo, policy="BALANCED")
        assert balanced["door_seal_confine"] is True
        assert balanced["door_step_depth"] == 0.0

        volume = build_product_options(cargo, policy="VOLUME_FIRST")
        assert volume["door_seal_confine"] is False
        assert volume["door_step_depth"] == 0.0

    def test_explicit_payload_override_wins(self):
        _, cargo = _setup()
        opts = build_product_options(
            cargo, policy="SAFETY_FIRST", payload={"doorStepDepth": 0.0})
        assert opts["door_step_depth"] == 0.0

    def test_no_door_cargo_has_no_safety_options(self):
        container, cargo = _mini_cargo()
        opts = build_product_options(cargo, policy="SAFETY_FIRST")
        assert opts["door_seal_confine"] is False
        assert opts["door_step_depth"] == 0.0

    def test_unknown_policy_normalizes_like_scoring(self):
        container, cargo = _setup()
        scenario = detect_scenario(cargo, container, requested_policy="NOT_A_POLICY")
        assert scenario["policy"] == get_policy("NOT_A_POLICY").key == "BALANCED"
        opts = build_product_options(cargo, policy="NOT_A_POLICY")
        assert opts["door_seal_confine"] is True
        assert opts["door_step_depth"] == 0.0  # BALANCED，不是 SAFETY 的 0.25 台阶

    def test_default_policy_still_product_safety(self):
        _, cargo = _setup()
        opts = build_product_options(cargo, policy=None)
        assert opts["door_seal_confine"] is True
        assert opts["door_step_depth"] == pytest.approx(0.25)


class TestKnnModel:
    def _samples(self):
        return [
            {"case_id": "a1", "x": [0.0] * 5, "policy": "SAFETY_FIRST", "score": 80},
            {"case_id": "a2", "x": [0.1] * 5, "policy": "SAFETY_FIRST", "score": 79},
            {"case_id": "b1", "x": [10.0] * 5, "policy": "VOLUME_FIRST", "score": 85},
            {"case_id": "b2", "x": [10.1] * 5, "policy": "VOLUME_FIRST", "score": 84},
        ]

    def test_predict_and_loo(self):
        model = fit(self._samples(), k=1)
        assert predict(model, [0.05] * 5)["policy"] == "SAFETY_FIRST"
        assert predict(model, [10.05] * 5)["policy"] == "VOLUME_FIRST"
        assert leave_one_out(self._samples(), k=1) == pytest.approx(1.0)


class TestSelector:
    def test_missing_model_falls_back_to_scenario(self, tmp_path):
        container, cargo = _setup()
        res = suggest_policy(cargo, container, model_path=str(tmp_path / "missing.json"))
        assert res["source"] == "fallback"
        assert res["policy"] == res["scenarioPolicy"]
        assert res["confidence"] == 0.0

    def test_learned_suggestion_for_supported_policy(self, tmp_path):
        container, cargo = _setup()
        feats = extract_features(cargo, container)
        x = to_vector(feats)
        model = fit([{"case_id": "train-1", "x": x, "policy": "BALANCED", "score": 80}] * 3)
        model["metrics"]["enabled"] = True
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model), encoding="utf-8")

        res = suggest_policy(cargo, container, model_path=str(path))
        assert res["source"] == "learned"
        assert res["policy"] == "BALANCED"
        assert res["confidence"] >= 0.99

    def test_safety_floor_blocks_volume_first_on_thin_door(self, tmp_path):
        """封门薄板场景：即使模型强烈建议 VOLUME_FIRST，也必须被安全底线否决。"""
        container, cargo = _setup()
        feats = extract_features(cargo, container)
        x = to_vector(feats)
        model = fit([{"case_id": "train-1", "x": x, "policy": "VOLUME_FIRST", "score": 90}] * 3)
        model["metrics"]["enabled"] = True
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model), encoding="utf-8")

        res = suggest_policy(cargo, container, model_path=str(path))
        assert res["policy"] != "VOLUME_FIRST"
        assert res["source"] == "fallback"
        assert "安全底线" in res["note"]


class TestTrainPipeline:
    def _write_dataset(self, path):
        rows = []
        # 12 个案例，两簇特征、两类标签；同簇得分一致 → 留一应 100%
        for i in range(12):
            label = "SAFETY_FIRST" if i < 6 else "VOLUME_FIRST"
            others = ["BALANCED", "VOLUME_FIRST" if i < 6 else "SAFETY_FIRST"]
            for policy, score in [(label, 85.0), (others[0], 70.0), (others[1], 60.0)]:
                features = {name: 0.0 for name in FEATURE_NAMES}
                features["sku_count"] = 1.0 if i < 6 else 10.0
                rows.append({
                    "case_id": f"case-{i}",
                    "policy": policy,
                    "features": features,
                    "evaluation": {
                        "score": score,
                        "hard_fail": False,
                        "tiers": {"T1": {"passed": True}},
                        "metrics": {"rigid_ratio": 1.0, "utilization_pct": 80.0},
                    },
                })
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_train_enables_on_valid_dataset(self, tmp_path):
        dataset = tmp_path / "dataset.jsonl"
        model_path = tmp_path / "model.json"
        report_path = tmp_path / "report.json"
        self._write_dataset(dataset)
        report = train(str(dataset), str(model_path), str(report_path), k=3)
        assert report["cases"] == 12
        assert report["enabled"] is True
        assert report["loo_accuracy"] == pytest.approx(1.0)
        model = json.loads(model_path.read_text(encoding="utf-8"))
        assert model["metrics"]["enabled"] is True
        assert len(model["samples"]) == 12

    def test_train_disables_on_single_label(self, tmp_path):
        dataset = tmp_path / "dataset.jsonl"
        with open(dataset, "w", encoding="utf-8") as f:
            for i in range(12):
                features = {name: 0.0 for name in FEATURE_NAMES}
                features["sku_count"] = float(i)
                f.write(json.dumps({
                    "case_id": f"case-{i}", "policy": "BALANCED", "features": features,
                    "evaluation": {"score": 80, "hard_fail": False,
                                   "tiers": {"T1": {"passed": True}},
                                   "metrics": {}},
                }, ensure_ascii=False) + "\n")
        report = train(str(dataset), str(tmp_path / "m.json"), str(tmp_path / "r.json"), k=3)
        assert report["enabled"] is False


class TestPublishedModel:
    """训练产物存在时，必须可被 selector/dashboard 安全消费。"""

    def test_model_file_if_present(self):
        from backend.solver_v2.learning.selector import DEFAULT_MODEL_PATH
        if not os.path.exists(DEFAULT_MODEL_PATH):
            pytest.skip("policy model not trained yet")
        model = json.load(open(DEFAULT_MODEL_PATH, encoding="utf-8"))
        assert model["feature_names"] == list(FEATURE_NAMES)
        assert model["samples"]
        metrics = model.get("metrics") or {}
        assert "enabled" in metrics
        assert 0.0 <= float(metrics.get("loo_accuracy", 0.0)) <= 1.0

    def test_selector_loads_published_model(self):
        from backend.solver_v2.learning.selector import DEFAULT_MODEL_PATH, load_model
        if not os.path.exists(DEFAULT_MODEL_PATH):
            pytest.skip("policy model not trained yet")
        assert load_model(DEFAULT_MODEL_PATH) is not None

    def test_disabled_published_model_falls_back(self):
        from backend.solver_v2.learning.selector import DEFAULT_MODEL_PATH, load_model
        model = load_model(DEFAULT_MODEL_PATH)
        if not model or (model.get("metrics") or {}).get("enabled"):
            pytest.skip("no disabled published model")
        container, cargo = _setup()
        res = suggest_policy(cargo, container, model_path=DEFAULT_MODEL_PATH)
        assert res["source"] == "fallback"
        assert res["policy"] == res["scenarioPolicy"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
