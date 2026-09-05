"""Default harness: the existing llmgateway ChatRequest loop."""

from __future__ import annotations

from .. import llmgateway
from .harness import NodeRequest, NodeResult


class RailHarness:
    name = "rail"

    async def run(self, req: NodeRequest) -> NodeResult:
        try:
            prov = llmgateway.get(req.provider_id)
        except llmgateway.ProviderError as e:
            return NodeResult(text="", error=str(e), harness=self.name)
        from .packages import get_package, package_tool_names
        pkg = get_package(req.package_id)
        allowed = package_tool_names(req.package_id, req.tools) if pkg else list(req.tools or [])
        chat = llmgateway.ChatRequest(
            messages=[{"role": "user", "content": req.user}],
            model=req.model,
            system=req.system,
            workspace=str(req.workspace),
            session_id=req.session_id,
            allowed_tools=allowed or None,
            package_writes=pkg.writes if pkg else None,
        )
        parts: list[str] = []
        in_tok = 0
        out_tok = 0
        err: str | None = None
        session = req.session_id
        try:
            async for ev in prov.chat_stream(chat):
                if isinstance(ev, llmgateway.TextChunk):
                    parts.append(ev.text or "")
                elif isinstance(ev, llmgateway.DoneChunk):
                    in_tok = int(ev.input_tokens or 0)
                    out_tok = int(ev.output_tokens or 0)
                    session = getattr(ev, "session_id", None) or session
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:400]
        return NodeResult(
            text="".join(parts),
            input_tokens=in_tok,
            output_tokens=out_tok,
            session_id=session,
            error=err,
            harness=self.name,
        )
