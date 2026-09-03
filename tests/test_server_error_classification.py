import unittest

from backend.api.error_response import classify_api_exception


class ApiErrorClassificationTests(unittest.TestCase):
    def test_no_valid_door_wall_is_input_constraint(self):
        status, payload = classify_api_exception(ValueError(
            "NO_VALID_DOOR_WALL: No explicitly door-eligible inventory"
        ))
        self.assertEqual(status, 422)
        self.assertEqual(payload["category"], "INPUT_CONSTRAINT")
        self.assertEqual(payload["code"], "NO_VALID_DOOR_WALL")
        self.assertNotIn("traceback", payload)

    def test_unknown_failure_remains_internal_error(self):
        status, payload = classify_api_exception(RuntimeError("unexpected"))
        self.assertEqual(status, 500)
        self.assertEqual(payload["category"], "INTERNAL_ERROR")
        self.assertFalse(payload["success"])
        self.assertIn("details", payload)

    def test_json_decode_error_classification(self):
        import json
        try:
            json.loads("{bad_json}")
        except json.JSONDecodeError as exc:
            status, payload = classify_api_exception(exc)
            self.assertEqual(status, 400)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["code"], "INPUT_VALIDATION_ERROR")
            self.assertIn("line", payload["details"])
            self.assertIn("col", payload["details"])

    def test_value_error_classification(self):
        status, payload = classify_api_exception(ValueError("Invalid dimensions: width must be positive"))
        self.assertEqual(status, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "INPUT_VALIDATION_ERROR")
        self.assertEqual(payload["details"]["exception_type"], "ValueError")


if __name__ == "__main__":
    unittest.main()
