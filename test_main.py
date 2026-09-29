import unittest

from main import check_claim, READY_FOR_REVIEW, NEEDS_INFORMATION


class TestClaimCompletenessChecker(unittest.TestCase):
    def test_complete_claim_is_ready_for_review(self):
        claim = {
            "policy_id": "POL-48213",
            "incident_date": "2026-09-10",
            "description": "Rear-end collision in parking lot, minor bumper damage.",
            "documents": ["police_report.pdf"],
        }
        result = check_claim(claim)
        self.assertEqual(result["status"], READY_FOR_REVIEW)
        self.assertEqual(result["missing"], [])

    def test_missing_incident_date_needs_information(self):
        claim = {
            "policy_id": "POL-77410",
            "incident_date": "",
            "description": "Kitchen fire, water damage to adjoining room.",
            "documents": ["photos.zip"],
        }
        result = check_claim(claim)
        self.assertEqual(result["status"], NEEDS_INFORMATION)
        self.assertIn("incident_date", result["missing"])

    def test_missing_documents_needs_information(self):
        claim = {
            "policy_id": "POL-1",
            "incident_date": "2026-01-01",
            "description": "Minor claim.",
            "documents": [],
        }
        result = check_claim(claim)
        self.assertEqual(result["status"], NEEDS_INFORMATION)
        self.assertIn("documents", result["missing"])

    def test_multiple_missing_fields_are_all_named(self):
        result = check_claim({"documents": []})
        self.assertEqual(result["status"], NEEDS_INFORMATION)
        self.assertEqual(
            set(result["missing"]),
            {"policy_id", "incident_date", "description", "documents"},
        )

    def test_never_returns_a_coverage_or_payout_decision(self):
        claim = {
            "policy_id": "POL-1",
            "incident_date": "2026-01-01",
            "description": "Minor claim.",
            "documents": ["report.pdf"],
        }
        result = check_claim(claim)
        result_text = json_lower(result)
        for word in ("approve", "deny", "decline", "pay"):
            self.assertNotIn(word, result_text)


def json_lower(result: dict) -> str:
    return str(result).lower()


if __name__ == "__main__":
    unittest.main()
