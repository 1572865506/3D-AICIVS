# -*- coding: utf-8 -*-
"""
Unit tests for Expert Review & Annotation API (Role D).
Tests GET /api/v1/annotations and POST /api/v1/annotations persistence.
"""
import unittest
import os
import json
import tempfile
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.server as server_module


class TestAnnotationAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_dir = server_module.ANNOTATIONS_DIR
        self.orig_file = server_module.ANNOTATIONS_FILE
        server_module.ANNOTATIONS_DIR = self.test_dir
        server_module.ANNOTATIONS_FILE = os.path.join(self.test_dir, 'annotations.jsonl')

    def tearDown(self):
        server_module.ANNOTATIONS_DIR = self.orig_dir
        server_module.ANNOTATIONS_FILE = self.orig_file
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_get_annotation(self):
        sample = {
            "solutionId": "sol_test_101",
            "rating": "GOLD",
            "score": 98,
            "tags": ["EXPERT_APPROVED", "DENSE_STACK"],
            "defects": [],
            "expertNotes": "优秀金牌方案，咬合紧凑无内部蜂窝空洞",
            "annotator": "Expert-3D",
        }
        saved = server_module.save_annotation(sample)
        self.assertIn("annotationId", saved)
        self.assertTrue(saved["annotationId"].startswith("ann_"))
        self.assertIn("timestamp", saved)

        # Retrieve all
        all_anns = server_module.get_annotations()
        self.assertEqual(len(all_anns), 1)
        self.assertEqual(all_anns[0]["solutionId"], "sol_test_101")
        self.assertEqual(all_anns[0]["rating"], "GOLD")

        # Save a second one
        sample2 = {
            "solutionId": "sol_test_102",
            "rating": "REJECT",
            "score": 45,
            "tags": ["HONEYCOMB_CAVITY"],
            "defects": [{"type": "HONEYCOMB_CAVITY", "note": "内部有大面积空腔"}],
            "expertNotes": "数字利用率虚高，内部空洞严重驳回",
            "annotator": "Expert-3D",
        }
        server_module.save_annotation(sample2)

        # Query with filter by solutionId
        filtered = server_module.get_annotations(filter_solution_id="sol_test_102")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["rating"], "REJECT")

        # Query with filter by rating
        gold_only = server_module.get_annotations(filter_rating="GOLD")
        self.assertEqual(len(gold_only), 1)
        self.assertEqual(gold_only[0]["solutionId"], "sol_test_101")


if __name__ == "__main__":
    unittest.main()
