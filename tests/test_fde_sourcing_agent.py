import json
import tempfile
import unittest
from pathlib import Path

from scripts.fde_sourcing_agent import (
    SourceHit,
    build_lead,
    merge_leads,
    score_hit,
    update_dashboard_data,
)


class FdeSourcingAgentTests(unittest.TestCase):
    def test_scores_complete_business_agent_profile_high(self):
        hit = SourceHit(
            name="Candidate",
            title="Forward Deployed AI Engineer",
            snippet=(
                "Built production AI Agent workflows with LangGraph, RAG, tool calling, "
                "Salesforce CRM integration, LangSmith tracing, eval harness, guardrails, "
                "FastAPI, Docker, and enterprise customer-facing delivery."
            ),
            platform="linkedin",
            url="https://linkedin.com/in/candidate",
        )

        scored = score_hit(hit)

        self.assertEqual(scored["tier"], "S")
        self.assertGreaterEqual(scored["score"], 9)
        self.assertIn("langgraph", [s.lower() for s in scored["group_hits"]["agent_building"]])
        self.assertTrue(scored["group_hits"]["harness_reliability"])

    def test_build_lead_uses_fde_track_and_stable_linkedin_id(self):
        hit = SourceHit(
            name="Jane Doe",
            title="AI Solutions Engineer",
            snippet="Enterprise AI agent with RAG, workflow automation, Python and customer delivery.",
            platform="linkedin",
            url="https://www.linkedin.com/in/jane-doe/",
        )

        lead = build_lead(hit, today="2026-08-05")

        self.assertEqual(lead["id"], "li-jane-doe")
        self.assertEqual(lead["talent_track"], "fde")
        self.assertTrue(lead["is_fde"])
        self.assertEqual(lead["linkedin"], "https://www.linkedin.com/in/jane-doe/")

    def test_negative_demo_only_profile_is_low_priority(self):
        hit = SourceHit(
            name="Demo Creator",
            title="Prompt Engineer and AI content creator",
            snippet="Student publishing beginner courses and ten-minute no-code agent demos.",
            platform="web",
            url="https://example.com/demo",
        )

        scored = score_hit(hit)

        self.assertLessEqual(scored["score"], 3)
        self.assertEqual(scored["tier"], "C")

    def test_bi_keyword_does_not_match_bio(self):
        hit = SourceHit(
            name="Repo Owner",
            title="Senior Engineer",
            snippet="GitHub repo with RAG and eval harness. Profile bio: backend engineer.",
            platform="github",
            url="https://github.com/repo-owner",
        )

        scored = score_hit(hit)

        self.assertNotIn("bi", scored["group_hits"]["business_domain"])
        self.assertIn("rag", scored["group_hits"]["agent_building"])

    def test_merge_preserves_manual_state_on_update(self):
        existing = {
            "meta": {"version": 1, "total": 1},
            "leads": [
                {
                    "id": "li-jane-doe",
                    "name": "Jane Doe",
                    "score": 5,
                    "tier": "B",
                    "talent_track": "fde",
                    "status": "contacted",
                    "note": "already reached out",
                    "priority": True,
                }
            ],
        }
        new = [
            {
                "id": "li-jane-doe",
                "name": "Jane Doe",
                "score": 9,
                "tier": "S",
                "talent_track": "fde",
                "status": "new",
                "priority": False,
            }
        ]

        merged, stats = merge_leads(existing, new)

        self.assertEqual(stats["updated"], 1)
        lead = merged["leads"][0]
        self.assertEqual(lead["score"], 9)
        self.assertEqual(lead["status"], "contacted")
        self.assertEqual(lead["note"], "already reached out")
        self.assertTrue(lead["priority"])

    def test_update_dashboard_replaces_leads_data_object(self):
        payload = {"meta": {"total": 1}, "leads": [{"id": "x"}]}
        html = '<script>\nconst LEADS_DATA = {"old": true};\nconst OTHER = 1;\n</script>\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dashboard.html"
            path.write_text(html, encoding="utf-8")

            update_dashboard_data(path, payload)

            updated = path.read_text(encoding="utf-8")
            self.assertIn(json.dumps(payload, ensure_ascii=False, indent=2), updated)
            self.assertIn("const OTHER = 1", updated)


if __name__ == "__main__":
    unittest.main()
