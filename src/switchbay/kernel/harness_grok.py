"""Grok Build as a harness for the same specialist job as Pi.

Uses the existing grok-build provider (MCP + stream). The package
contract is the system prompt + CE tools, not a Pi extension.
"""

from __future__ import annotations

from .harness import NodeRequest, NodeResult
from .harness_rail import RailHarness


class GrokBuildHarness(RailHarness):
    name = "grok-build"

    async def run(self, req: NodeRequest) -> NodeResult:
        from dataclasses import replace
        if not req.provider_id:
            req = replace(req, provider_id="grok-build")
        result = await super().run(req)
        result.harness = self.name
        return result
