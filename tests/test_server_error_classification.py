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


if __name__ == "__main__":
    unittest.main()
