"""Slideshow PDF label, clearance, catalog, destination, and encryption."""

from __future__ import annotations

import base64
import getpass
import hashlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pypdf import PdfReader, PdfWriter

from switchbay import admin_policy, pdf_export, tools  # noqa: F401  (breaks an import cycle)
from switchbay.federation import audit, exclusion, session_label
from switchbay.federation.mounts import Source
from switchbay.federation.tools_reg import add_source


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBAY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SWITCHBAY_ADMIN_POLICY", str(tmp_path / "admin.json"))
    (tmp_path / "admin.json").write_text("{}\n", encoding="utf-8")
    admin_policy.reset_cache()
    yield tmp_path
    admin_policy.reset_cache()


def _admin(workspace: Path, data: dict) -> None:
    (workspace / "admin.json").write_text(json.dumps(data), encoding="utf-8")
    admin_policy.reset_cache()


def _deck(workspace: Path, slug: str = "demo", **meta: object) -> None:
    folder = workspace / "slideshows" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text("<!doctype html><title>deck</title><p>slide</p>", encoding="utf-8")
    payload = {"title": meta.get("title") or slug}
    payload.update(meta)
    (folder / "deck.json").write_text(json.dumps(payload), encoding="utf-8")


def _session(workspace: Path, label: str) -> None:
    session_label.set_current("chat", workspace)
    data = session_label._load(workspace)
    data["chat"] = label
    data[session_label._ACTIVE] = "chat"
    session_label._save(workspace, data)


def _pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=320, height=180)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _reader(path: Path, password: str = "") -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted and password:
        reader.decrypt(password)
    return reader


def _stamp_count(reader: PdfReader) -> int:
    found = 0
    for page in reader.pages:
        contents = page.get_contents()
        if contents is not None and b"SWITCHBAY" in contents.get_data():
            found += 1
    return found


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, code: int, payload: object, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode())


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_confidential_session_exports_without_a_dialog(workspace: Path):
    _deck(workspace)
    _session(workspace, "confidential")
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    assert decision["status"] == 200, decision
    assert decision["body"]["label"] == "confidential"
    assert "needs_dialog" not in decision["body"]
    outcome = pdf_export.finish(workspace, decision["body"], _pdf(pages=2))
    assert outcome["status"] == 200, outcome
    path = workspace / "vault" / "exports" / "demo.pdf"
    reader = _reader(path)
    assert _stamp_count(reader) == 2
    assert str(reader.metadata.get("/SwitchbayLabel")) == "confidential"
    xmp = reader.xmp_metadata.stream.get_data()
    assert b"confidential" in xmp
    assert b"urn:switchbay:classification:1.0" in xmp
    assert str(reader.metadata.get("/SwitchbayUser")) == getpass.getuser()
    assert str(reader.metadata.get("/SwitchbayVersion"))
    assert str(reader.metadata.get("/SwitchbayWorkspace")) == str(workspace.resolve())
    assert b"SwitchbayTimestamp" in xmp or str(reader.metadata.get("/SwitchbayTimestamp"))
    row = next(item for item in audit.read(workspace) if item["event"] == "export")
    assert row["label"] == "confidential"
    assert row["sources"] == []
    assert row["destination_class"] == "inside"
    assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert row["user"] == getpass.getuser()
    assert row["ts"]


def test_public_label_is_metadata_only(workspace: Path):
    _deck(workspace)
    _session(workspace, "public")
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    outcome = pdf_export.finish(workspace, decision["body"], _pdf())
    assert outcome["status"] == 200
    reader = _reader(workspace / "vault" / "exports" / "demo.pdf")
    assert _stamp_count(reader) == 0
    assert str(reader.metadata.get("/SwitchbayLabel")) == "public"
    assert b"SWITCHBAY PUBLIC" not in (workspace / "vault" / "exports" / "demo.pdf").read_bytes()


def test_included_content_raises_the_file_label_within_clearance(workspace: Path):
    _deck(workspace, slides=[{"heading": "Numbers", "classification": "confidential"}])
    _session(workspace, "public")
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    assert decision["status"] == 200
    assert decision["body"]["label"] == "confidential"
    outcome = pdf_export.finish(workspace, decision["body"], _pdf())
    assert outcome["body"]["stamped"] is True


def test_content_above_clearance_is_refused(workspace: Path):
    _admin(workspace, {"exports": {"clearance": "confidential", "max_ceiling": "restricted"}})
    _deck(workspace, slides=[{"heading": "Board", "classification": "restricted", "source_ref": "local:board"}])
    _session(workspace, "confidential")
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    assert decision["status"] == 403
    assert "above the clearance" in decision["body"]["error"]
    assert not (workspace / "vault" / "exports" / "demo.pdf").exists()
    assert any(row["event"] == "refused_write" for row in audit.read(workspace))


def test_max_ceiling_and_per_user_clearance_fail_closed(workspace: Path):
    _admin(workspace, {"exports": {"clearance": "restricted", "max_ceiling": "internal"}})
    _deck(workspace, slides=[{"classification": "confidential"}])
    _session(workspace, "public")
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 403
    _admin(workspace, {"exports": {"clearance": "restricted", "clearance_by_user": {getpass.getuser(): "public"}}})
    _deck(workspace, slides=[{"classification": "internal"}])
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 403
    _admin(workspace, {"exports": {"clearance": "not-a-label"}})
    assert pdf_export.effective_ceiling() == "public"
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 403


def test_deny_source_and_exclusion_rule_refuse(workspace: Path):
    _deck(workspace, slides=[{"heading": "customer list", "source_ref": "deny:customer"}])
    _session(workspace, "internal")
    denied = pdf_export.prepare(workspace, {"slug": "demo"})
    assert denied["status"] == 403
    assert "cannot be exported" in denied["body"]["error"]
    _deck(workspace, slides=[{"heading": "customer list", "source_ref": "readonly:customer"}])
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 200
    exclusion.save(workspace, [{"id": "r1", "description": "customer list", "decision": "deny"}])
    blocked = pdf_export.prepare(workspace, {"slug": "demo"})
    assert blocked["status"] == 403
    assert "exclusion rule" in blocked["body"]["error"]
    exclusion.save(workspace, [{"id": "r1", "description": "customer list", "decision": "ask"}])
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 200


def test_catalog_export_false_and_errors_fail_closed(workspace: Path):
    class Handler(_Handler):
        def do_POST(self) -> None:
            self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {"content": [
                {"type": "text", "text": json.dumps({"read": True, "write": False, "export": False})},
            ]}})

    server, origin = _serve(Handler)
    try:
        add_source(workspace, Source(id="iq", kind="workiq", url=origin + "/mcp"))
        _deck(workspace, slides=[{"source_ref": "workiq:orders"}])
        _session(workspace, "public")
        refused = pdf_export.prepare(workspace, {"slug": "demo"})
        assert refused["status"] == 403
        assert "workiq:orders" in refused["body"]["error"]
    finally:
        server.shutdown()
    add_source(workspace, Source(id="down", kind="workiq", url="http://127.0.0.1:1/mcp"))
    _deck(workspace, slides=[{"source_ref": "workiq:orders"}])
    assert pdf_export.prepare(workspace, {"slug": "demo"})["status"] == 403


def test_outside_boundary_dialog_ok_cancel_and_always(workspace: Path):
    _deck(workspace)
    _session(workspace, "confidential")
    outside = workspace / "Dropbox" / "deck.pdf"
    first = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(outside)})
    assert first["status"] == 409
    assert first["body"]["needs_dialog"] is True
    assert first["body"]["choices"] == ["ok", "always", "cancel"]
    assert first["body"]["destination_class"] == "outside"
    cancelled = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(outside), "confirm": "cancel"})
    assert cancelled["status"] == 403
    assert not outside.exists()
    allowed = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(outside), "confirm": "ok"})
    assert allowed["status"] == 200
    outcome = pdf_export.finish(workspace, allowed["body"], _pdf())
    assert outcome["status"] == 200
    assert outside.is_file()
    assert outcome["body"]["destination_class"] == "outside"
    remembered = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(outside), "confirm": "always"})
    assert remembered["status"] == 200
    again = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(outside)})
    assert again["status"] == 200


def test_trust_boundary_allowlist_is_inside_and_forbid_has_no_dialog(workspace: Path):
    folder = workspace / "Dropbox"
    _admin(workspace, {"paths": {"trust_boundary": [str(folder)]}})
    _deck(workspace)
    _session(workspace, "public")
    inside = pdf_export.prepare(workspace, {"slug": "demo", "destination": str(folder / "deck.pdf")})
    assert inside["status"] == 200
    assert inside["body"]["destination_class"] == "inside"
    _admin(workspace, {"exports": {"forbid_outside_boundary": True}})
    outside = workspace / "Dropbox" / "other.pdf"
    # The allowlist above was replaced, so Dropbox is outside again.
    refused = pdf_export.prepare(workspace, {
        "slug": "demo", "destination": str(outside), "confirm": "ok",
    })
    assert refused["status"] == 403
    assert "forbids" in refused["body"]["error"]
    assert "needs_dialog" not in refused["body"]


def test_password_and_certificate_encryption_are_optional_aes_256(workspace: Path):
    _deck(workspace)
    _session(workspace, "confidential")
    missing = pdf_export.prepare(workspace, {"slug": "demo", "encrypt": {"mode": "password", "password": ""}})
    assert missing["status"] == 400
    decision = pdf_export.prepare(workspace, {
        "slug": "demo", "encrypt": {"mode": "password", "password": "correct horse"},
    })
    outcome = pdf_export.finish(workspace, decision["body"], _pdf())
    assert outcome["body"]["encryption"] == "password"
    path = workspace / "vault" / "exports" / "demo.pdf"
    locked = PdfReader(str(path))
    assert locked.is_encrypted
    encrypt = locked.trailer["/Encrypt"].get_object()
    assert str(encrypt["/CF"]["/StdCF"]["/CFM"]) == "/AESV3"
    assert int(encrypt["/Length"]) == 256
    assert locked.decrypt("correct horse")
    assert _stamp_count(locked) == 1
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    cert = pdf_export.prepare(workspace, {
        "slug": "demo", "encrypt": {"mode": "certificate", "certificate": pem},
    })
    saved = pdf_export.finish(workspace, cert["body"], _pdf())
    assert saved["body"]["encryption"] == "certificate"
    wrap = json.loads(Path(str(path) + ".wrap.json").read_text(encoding="utf-8"))
    assert wrap["pdf_encryption"] == "AES-256"
    assert wrap["alg"] == "RSA-OAEP-SHA256"
    password = key.decrypt(
        base64.b64decode(wrap["wrapped_key"]),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    opened = PdfReader(str(path))
    assert opened.decrypt(password.decode())
    assert _stamp_count(opened) == 1


def test_purview_metadata_and_endpoint_fail_closed(workspace: Path):
    guid = "2096f6a2-d2f7-48be-b329-b73aaa526e5d"
    site = "cb46c030-1825-4e81-a295-151c039dbf02"
    _admin(workspace, {"exports": {"purview": {
        "site_id": site,
        "labels": {"confidential": guid},
    }}})
    _deck(workspace, slides=[{"source_ref": "memo:1"}])
    _session(workspace, "confidential")
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    outcome = pdf_export.finish(workspace, decision["body"], _pdf())
    assert outcome["body"]["purview"] == "metadata"
    assert outcome["body"]["encryption"] == ""
    raw = (workspace / "vault" / "exports" / "demo.pdf").read_bytes()
    assert guid.encode() in raw
    reader = _reader(workspace / "vault" / "exports" / "demo.pdf")
    assert str(reader.metadata.get(f"/MSIP_Label_{guid}_Enabled")) == "true"
    assert str(reader.metadata.get(f"/MSIP_Label_{guid}_SiteId")) == site
    assert str(reader.metadata.get(f"/MSIP_Label_{guid}_Name")) == "confidential"
    assert b"MSIP_Label_" in reader.xmp_metadata.stream.get_data()
    row = next(item for item in audit.read(workspace) if item["event"] == "export")
    assert row["sources"] == ["memo:1"]

    seen: dict[str, str] = {}

    class Handler(_Handler):
        def do_POST(self) -> None:
            seen["label"] = self.headers.get("X-Switchbay-Label") or ""
            seen["id"] = self.headers.get("X-Switchbay-Label-Id") or ""
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            self._send(200, body + b"\n% switchbay-labeled\n", "application/pdf")

    server, origin = _serve(Handler)
    try:
        _admin(workspace, {"exports": {"purview": {
            "endpoint": origin + "/label",
            "site_id": site,
            "labels": {"confidential": guid},
        }}})
        decision = pdf_export.prepare(workspace, {
            "slug": "demo", "encrypt": {"mode": "password", "password": "should-be-ignored"},
        })
        assert decision["body"]["encrypt"] is None
        outcome = pdf_export.finish(workspace, decision["body"], _pdf())
        assert outcome["status"] == 200, outcome
        assert outcome["body"]["purview"] == "endpoint"
        assert outcome["body"]["encryption"] == ""
        stored = (workspace / "vault" / "exports" / "demo.pdf").read_bytes()
        assert stored.endswith(b"% switchbay-labeled\n")
        assert seen["label"] == "confidential"
        assert seen["id"] == guid
    finally:
        server.shutdown()

    class Down(_Handler):
        def do_POST(self) -> None:
            self._send(503, b"down", "text/plain")

    server, origin = _serve(Down)
    try:
        target = workspace / "vault" / "exports" / "demo.pdf"
        target.unlink(missing_ok=True)
        _admin(workspace, {"exports": {"purview": {"endpoint": origin + "/label"}}})
        decision = pdf_export.prepare(workspace, {"slug": "demo"})
        failed = pdf_export.finish(workspace, decision["body"], _pdf())
        assert failed["status"] == 502
        assert not target.exists()
    finally:
        server.shutdown()

    target = workspace / "vault" / "exports" / "demo.pdf"
    target.unlink(missing_ok=True)
    _admin(workspace, {"exports": {"purview": {"endpoint": "http://127.0.0.1:1/label"}}})
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    unreachable = pdf_export.finish(workspace, decision["body"], _pdf())
    assert unreachable["status"] == 502
    assert "unreachable" in unreachable["body"]["error"]
    assert not target.exists()

    class NotPdf(_Handler):
        def do_POST(self) -> None:
            self._send(200, b"hello", "text/plain")

    server, origin = _serve(NotPdf)
    try:
        target = workspace / "vault" / "exports" / "demo.pdf"
        target.unlink(missing_ok=True)
        _admin(workspace, {"exports": {"purview": {"endpoint": origin + "/label"}}})
        decision = pdf_export.prepare(workspace, {"slug": "demo"})
        bad = pdf_export.finish(workspace, decision["body"], _pdf())
        assert bad["status"] == 502
        assert not target.exists()
    finally:
        server.shutdown()


def test_purview_mcp_endpoint_and_egress_refusal(workspace: Path, monkeypatch):
    class Handler(_Handler):
        def do_POST(self) -> None:
            body = self._json()
            args = (body.get("params") or {}).get("arguments") or {}
            pdf = base64.b64decode(args.get("pdf_base64") or "")
            self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {"content": [
                {"type": "text", "text": json.dumps({"pdf_base64": base64.b64encode(pdf).decode()})},
            ]}})

    server, origin = _serve(Handler)
    try:
        _deck(workspace)
        _session(workspace, "internal")
        _admin(workspace, {"exports": {"purview": {"endpoint": origin + "/mcp", "transport": "mcp"}}})
        decision = pdf_export.prepare(workspace, {"slug": "demo"})
        outcome = pdf_export.finish(workspace, decision["body"], _pdf())
        assert outcome["status"] == 200, outcome
        assert outcome["body"]["purview"] == "endpoint"
        assert _stamp_count(_reader(workspace / "vault" / "exports" / "demo.pdf")) == 1
    finally:
        server.shutdown()
    target = workspace / "vault" / "exports" / "demo.pdf"
    target.unlink(missing_ok=True)
    monkeypatch.delenv("SWITCHBAY_PROFILE", raising=False)
    _admin(workspace, {
        "profile": "enterprise",
        "exports": {"purview": {"endpoint": "http://label.example/apply"}},
    })
    decision = pdf_export.prepare(workspace, {"slug": "demo"})
    blocked = pdf_export.finish(workspace, decision["body"], _pdf())
    assert blocked["status"] == 502
    assert "egress" in blocked["body"]["error"]
    assert not target.exists()
