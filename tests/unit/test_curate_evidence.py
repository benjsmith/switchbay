"""Curate success is grounded in work, not outage-keyword matching."""

from __future__ import annotations

from switchbay.agents import orchestration as orch
from switchbay.agents import orchestration_health as health


def test_research_rate_limit_prose_is_not_outage():
    assert health.looks_like_outage(
        '{"findings":[{"claim":"The API uses 429 for rate limit errors; retries use backoff.","confidence":0.9}]}'
    ) is None
    assert health.looks_like_outage(
        'Curated failure analysis. The source says "too many requests"; this is evidence, not a transport error.'
    ) is None
    banner = "You've hit your weekly limit - resets Aug 26 at 11pm (Europe/Zurich)"
    assert health.looks_like_outage(banner) == "weekly_limit"


def test_receipt_had_work_is_page_diff_not_tool_count():
    assert orch._receipt_had_work({
        "wiki_pages_landed": 1,
        "wiki_pages_changed": ["wiki/concepts/x.md"],
        "wiki_commit_diff": " x.md | 3 +++",
    })
    assert not orch._receipt_had_work({
        "wiki_pages_landed": 0,
        "wiki_tool_commits": 4,
        "wiki_pages_changed": [],
        "output": "called ce_wave_prime",
    })
    assert not orch._receipt_had_work({
        "wiki_head_before": "aaa",
        "wiki_head_after": "bbb",
        "wiki_pages_landed": 0,
        "wiki_pages_changed": [],
        "wiki_commit_diff": "",
        "wiki_committed": True,
    }), "empty SHA move is not useful curation"
    assert orch._receipt_had_work({
        "wiki_pages_landed": 0,
        "wiki_pages_changed": ["wiki/fixture.md"],
        "wiki_commit_diff": " fixture.md | 1 +-",
    })
