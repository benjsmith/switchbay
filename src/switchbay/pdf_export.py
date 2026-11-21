"""Slideshow PDF export at the session label.

The file's label is the higher of the session floor and the labels of
the slides it includes. A confidential session therefore writes a
confidential PDF without a dialog. The export stops only when included
content is above the clearance, a source reference cannot be taken out,
an exclusion rule denies it, or an admin forbids the destination.

A label above public is drawn as a header and footer band on every
page. Info-dict and XMP metadata are written for every label, including
public. When ``exports.purview`` maps the label to a GUID, the same
metadata carries the Microsoft Information Protection keys DLP tools
read. That metadata does not encrypt the file. Encryption-by-policy is
the org labeling endpoint: the PDF is replaced with the service's
bytes, and a configured endpoint that does not return a PDF refuses
the export. With no endpoint, a person can optionally encrypt with a
password or a recipient certificate (AES-256). That option is never
applied unless they ask.

Run: python -m switchbay serve --workspace PATH
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import io
import json
import os
import re
import secrets
import time
import uuid
import xml.sax.saxutils as xml_escape
from pathlib import Path
from typing import Any

from . import __version__, html_decks
from .federation import access, audit, boundary, classify, exclusion, session_label
from .federation.policy import cloud_sync_name

# Same cap as the catalog and live-graph clients. Not a retry.
_LABEL_TIMEOUT_S = 4
_LABELS = ("public", "internal", "confidential", "restricted")
_NS = "urn:switchbay:classification:1.0"
_CITE = re.compile(
    r"\(\s*(?P<kind>vault|table|figure|graph|capture)\s*:\s*(?P<body>[^)\n]+)\)"
)
_ATTR_REF = re.compile(r"""data-source-ref\s*=\s*["']([^"']+)["']""", re.I)
_ATTR_LABEL = re.compile(r"""data-classification\s*=\s*["']([^"']+)["']""", re.I)


class ExportError(Exception):
    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


def exports_policy() -> dict[str, Any]:
    from . import admin_policy
    raw = admin_policy.load().get("exports")
    base: dict[str, Any] = {
        "clearance": "restricted",
        "max_ceiling": "restricted",
        "clearance_by_user": {},
        "forbid_outside_boundary": False,
        "purview": {
            "site_id": "",
            "endpoint": "",
            "transport": "",
            "source_id": "",
            "labels": {},
        },
    }
    if not isinstance(raw, dict):
        return base
    purview = dict(base["purview"])
    nested = raw.get("purview")
    if isinstance(nested, dict):
        purview.update(nested)
    for key, value in raw.items():
        if key != "purview":
            base[key] = value
    base["purview"] = purview
    return base


def _config_rank(label: str) -> int:
    """Unknown admin labels fail closed to public."""
    key = (label or "").strip().lower()
    if key not in _LABELS:
        return 0
    return classify.rank(key)


def _lower_label(left: str, right: str) -> str:
    return classify.name_for(min(_config_rank(left), _config_rank(right)))


def effective_ceiling() -> str:
    section = exports_policy()
    user = _user()
    by_user = section.get("clearance_by_user") or {}
    chosen = ""
    if isinstance(by_user, dict):
        chosen = str(by_user.get(user) or "").strip()
    clearance = chosen or str(section.get("clearance") or "restricted")
    cap = str(section.get("max_ceiling") or "restricted")
    return _lower_label(clearance, cap)


def policy_view() -> dict[str, Any]:
    section = exports_policy()
    endpoint = str((section.get("purview") or {}).get("endpoint") or "").strip()
    return {
        "clearance": effective_ceiling(),
        "forbid_outside_boundary": bool(section.get("forbid_outside_boundary")),
        "purview_endpoint": bool(endpoint),
        "encryption_optional": not bool(endpoint),
    }


def _user() -> str:
    try:
        return getpass.getuser() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _err(message: str, status: int) -> dict[str, Any]:
    return {"status": status, "body": {"error": message}}


def _refuse(workspace: Path, why: str, *, label: str, sources: list[str], destination_class: str) -> None:
    audit.record(
        workspace, "refused_write",
        why=why, label=label or None, sources=sources, user=_user(),
        destination_class=destination_class or None,
    )


def _rule_paths(workspace: Path) -> list[Path]:
    from . import workspaces
    return [
        workspaces.config_dir() / "export-destination-rules.json",
        workspace / ".workbench" / "export-destination-rules.json",
    ]


def _read_rules(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _outside_remembered(workspace: Path) -> bool:
    for path in _rule_paths(workspace):
        for row in _read_rules(path):
            if str(row.get("decision") or "") == "allow":
                return True
    return False


def _remember_outside(workspace: Path) -> None:
    from . import atomicio, workspaces
    path = workspaces.config_dir() / "export-destination-rules.json"
    rows = _read_rules(path)
    if not any(str(row.get("decision") or "") == "allow" for row in rows):
        rows.append({
            "id": uuid.uuid4().hex[:8],
            "description": "Save a PDF outside the trust boundary",
            "decision": "allow",
            "scope": "global",
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        atomicio.write_json_atomic(path, rows)
    audit.record(workspace, "export_allow", scope="global", user=_user())


def destination_class(path: Path) -> tuple[str, str]:
    """``inside`` or ``outside``, and the sync service name when outside.

    The cloud-sync detector is the same one the trust boundary uses.
    A path under ``paths.trust_boundary`` is inside even when it sits
    in a synced folder. The profile does not gate this check.
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    service = cloud_sync_name(resolved) or ""
    if not service:
        return "inside", ""
    text = str(resolved)
    for prefix in boundary.allowlist():
        try:
            root = str(Path(prefix).expanduser().resolve())
        except OSError:
            root = str(Path(prefix).expanduser())
        if text == root or text.startswith(root + os.sep):
            return "inside", ""
    return "outside", service


def _meta(workspace: Path, slug: str) -> dict[str, Any]:
    path = html_decks.deck_dir(workspace, slug) / "deck.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _html(workspace: Path, slug: str) -> str:
    entry = html_decks.entry_html(workspace, slug)
    if entry is None:
        return ""
    try:
        return entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _visible(html: str) -> str:
    stripped = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", text).strip()


def _add_ref(refs: list[str], value: object) -> None:
    text = str(value or "").strip()
    if text and text not in refs:
        refs.append(text)


def _add_label(labels: list[str], value: object) -> None:
    text = str(value or "").strip().lower()
    if text:
        labels.append(text)


def _front_source(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    block = text[4:end] if end >= 0 else ""
    for line in block.splitlines():
        if line.startswith("source_ref:"):
            return line.split(":", 1)[1].strip()
    return ""


def _citation_refs(workspace: Path, text: str, refs: list[str]) -> None:
    from .federation import broker, citations
    for match in _CITE.finditer(text or ""):
        kind = match.group("kind")
        body = match.group("body").strip()
        if kind == "graph":
            mount, page, rev = citations.parse(body)
            cached = citations.cached_page(workspace, mount, rev, page) if mount else None
            if isinstance(cached, dict):
                _add_ref(refs, cached.get("source_ref"))
            continue
        if kind == "capture":
            cid = body.split("#", 1)[0].strip()
            path = broker._dir(workspace) / f"{cid}.json"
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
                if isinstance(data, dict):
                    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
                    _add_ref(refs, args.get("source_ref") or data.get("source_ref"))
            continue
        found = classify._resolve_file(workspace, body.split("#", 1)[0].strip())
        if found is not None:
            _add_ref(refs, _front_source(found))


def collect(workspace: Path, slug: str) -> dict[str, Any]:
    """Label, source refs, title, and the text exclusion rules see."""
    meta = _meta(workspace, slug)
    html = _html(workspace, slug)
    labels = [session_label.floor(workspace)]
    refs: list[str] = []
    headings: list[str] = []
    _add_label(labels, meta.get("classification"))
    for key in ("source_ref",):
        _add_ref(refs, meta.get(key))
    for key in ("source_refs", "sources"):
        values = meta.get(key) or []
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for item in values:
                _add_ref(refs, item)
    slides = meta.get("slides") or []
    blob_parts = [str(meta.get("title") or ""), html]
    if isinstance(slides, list):
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            _add_label(labels, slide.get("classification"))
            _add_ref(refs, slide.get("source_ref"))
            for key in ("source_refs", "sources"):
                values = slide.get(key) or []
                if isinstance(values, str):
                    values = [values]
                if isinstance(values, list):
                    for item in values:
                        _add_ref(refs, item)
            for key in ("heading", "title", "body"):
                text = str(slide.get(key) or "").strip()
                if text:
                    headings.append(text)
                    blob_parts.append(text)
    for found in _ATTR_REF.findall(html):
        _add_ref(refs, found)
    for found in _ATTR_LABEL.findall(html):
        _add_label(labels, found)
    blob = "\n".join(blob_parts)
    _add_label(labels, classify.derived(workspace, blob))
    _citation_refs(workspace, blob, refs)
    title = str(meta.get("title") or slug)
    return {
        "label": classify.highest(*labels),
        "sources": refs,
        "title": title,
        "action": " ".join(
            ["export slideshow pdf", slug, f"label {classify.highest(*labels)}", title, *refs, *headings, _visible(html)]
        )[:8000],
    }


def _resolve_destination(workspace: Path, slug: str, raw: object) -> Path:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return workspace / "vault" / "exports" / f"{slug}.pdf"
    if not isinstance(raw, str) or "\x00" in raw:
        raise ExportError("invalid export destination", 400)
    dest = Path(raw).expanduser()
    if not dest.is_absolute():
        dest = (workspace / dest)
    try:
        dest = dest.resolve()
    except OSError:
        dest = dest.expanduser()
    if raw.endswith(("/", os.sep)) or (dest.exists() and dest.is_dir()):
        dest = dest / f"{slug}.pdf"
    return dest


def _encrypt_spec(body: dict[str, Any]) -> dict[str, str] | None:
    """The optional AES-256 request, or None when Purview owns protection."""
    endpoint = str((exports_policy().get("purview") or {}).get("endpoint") or "").strip()
    spec = body.get("encrypt")
    if endpoint or not spec:
        return None
    if not isinstance(spec, dict):
        raise ExportError("invalid encryption request", 400)
    mode = str(spec.get("mode") or "").strip().lower()
    if mode == "password":
        password = spec.get("password")
        if not isinstance(password, str) or not password:
            raise ExportError("a password is required", 400)
        if len(password) > 128:
            raise ExportError("password is too long", 400)
        return {"mode": "password", "password": password}
    if mode == "certificate":
        pem = spec.get("certificate")
        if not isinstance(pem, str) or "BEGIN" not in pem:
            raise ExportError("a recipient certificate is required", 400)
        if len(pem) > 65536:
            raise ExportError("recipient certificate is too long", 400)
        _load_public_key(pem)
        return {"mode": "certificate", "certificate": pem}
    raise ExportError("encryption mode must be password or certificate", 400)


def prepare(workspace: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Decide whether this export may render. Does not write a file."""
    slug = str((body or {}).get("slug") or "").strip()
    if not html_decks.is_valid_slug(slug):
        return _err("invalid slideshow slug", 400)
    if html_decks.entry_html(workspace, slug) is None:
        return _err("slideshow not found", 404)
    found = collect(workspace, slug)
    label = str(found["label"])
    sources = list(found["sources"])
    ceiling = effective_ceiling()
    if classify.above(label, ceiling):
        why = f"included content is {label}, above the clearance {ceiling}"
        _refuse(workspace, why, label=label, sources=sources, destination_class="")
        return _err(why, 403)
    for ref in sources:
        decision = access.checker().check(ref, workspace=workspace)
        if not (decision.read and decision.export):
            why = f"source {ref} cannot be exported"
            _refuse(workspace, why, label=label, sources=sources, destination_class="")
            return _err(why, 403)
    if exclusion.classify_action(str(found["action"]), workspace=workspace) == "deny":
        why = "an exclusion rule denies this export"
        _refuse(workspace, why, label=label, sources=sources, destination_class="")
        return _err(why, 403)
    try:
        dest = _resolve_destination(workspace, slug, (body or {}).get("destination"))
    except ExportError as exc:
        return _err(str(exc), exc.status)
    klass, service = destination_class(dest)
    section = exports_policy()
    if klass == "outside" and bool(section.get("forbid_outside_boundary")):
        why = f"{dest} is outside the trust boundary and admin policy forbids that destination"
        _refuse(workspace, why, label=label, sources=sources, destination_class="outside")
        return _err(why, 403)
    confirm = str((body or {}).get("confirm") or "").strip().lower()
    if klass == "outside" and not _outside_remembered(workspace):
        if confirm == "cancel":
            why = "export destination cancelled"
            _refuse(workspace, why, label=label, sources=sources, destination_class="outside")
            return _err(why, 403)
        if confirm == "always":
            _remember_outside(workspace)
        elif confirm != "ok":
            return {
                "status": 409,
                "body": {
                    "needs_dialog": True,
                    "choices": ["ok", "always", "cancel"],
                    "destination_class": "outside",
                    "service": service or "a synced folder",
                    "path": str(dest),
                    "label": label,
                },
            }
    try:
        encrypt = _encrypt_spec(body or {})
    except ExportError as exc:
        return _err(str(exc), exc.status)
    return {
        "status": 200,
        "body": {
            "slug": slug,
            "title": str(found["title"]),
            "label": label,
            "sources": sources,
            "destination": str(dest),
            "destination_class": klass,
            "stamp": classify.rank(label) > classify.rank("public"),
            "encrypt": encrypt,
        },
    }


def _pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _stamp(writer: Any, label: str) -> None:
    from pypdf import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    token = _pdf_text(f"SWITCHBAY {label.upper()}")
    for page in writer.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        band = 16.0
        ops = (
            "q\n"
            "0.45 0.07 0.09 rg\n"
            f"0 {height - band:.2f} {width:.2f} {band:.2f} re f\n"
            f"0 0 {width:.2f} {band:.2f} re f\n"
            "1 1 1 rg\n"
            "BT /SwitchbayStamp 9 Tf\n"
            f"8 {height - 12:.2f} Td ({token}) Tj ET\n"
            "BT /SwitchbayStamp 9 Tf\n"
            f"8 4 Td ({token}) Tj ET\n"
            "Q\n"
        ).encode("ascii")
        overlay = PageObject.create_blank_page(width=width, height=height)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        })
        overlay[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/SwitchbayStamp"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(ops)
        overlay[NameObject("/Contents")] = stream
        page.merge_page(overlay)


def _xmp(fields: dict[str, str], msip: dict[str, str]) -> bytes:
    def tag(ns: str, name: str, value: str) -> str:
        return f"<{ns}:{name}>{xml_escape.escape(value)}</{ns}:{name}>"
    body = [
        tag("sb", "Label", fields["label"]),
        tag("sb", "Workspace", fields["workspace"]),
        tag("sb", "User", fields["user"]),
        tag("sb", "Timestamp", fields["timestamp"]),
        tag("sb", "Version", fields["version"]),
        tag("pdfx", "SwitchbayLabel", fields["label"]),
        tag("pdfx", "SwitchbayWorkspace", fields["workspace"]),
        tag("pdfx", "SwitchbayUser", fields["user"]),
        tag("pdfx", "SwitchbayTimestamp", fields["timestamp"]),
        tag("pdfx", "SwitchbayVersion", fields["version"]),
        tag("dc", "creator", fields["user"]),
        tag("pdf", "Producer", f"Switchbay {fields['version']}"),
        tag("xmp", "CreatorTool", f"Switchbay {fields['version']}"),
    ]
    for key, value in msip.items():
        body.append(tag("pdfx", key, value))
    xml = (
        "<?xpacket begin=\"\ufeff\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n"
        "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\">\n"
        "<rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n"
        "<rdf:Description rdf:about=\"\" "
        "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" "
        "xmlns:pdf=\"http://ns.adobe.com/pdf/1.3/\" "
        "xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\" "
        "xmlns:pdfx=\"http://ns.adobe.com/pdfx/1.3/\" "
        f"xmlns:sb=\"{_NS}\">\n"
        + "\n".join(body)
        + "\n</rdf:Description>\n</rdf:RDF>\n</x:xmpmeta>\n"
        "<?xpacket end=\"w\"?>\n"
    )
    return xml.encode("utf-8")


def _msip(label: str, *, stamped: bool, encrypted: bool, when: str) -> dict[str, str]:
    purview = exports_policy().get("purview") or {}
    labels = purview.get("labels") if isinstance(purview, dict) else {}
    guid = ""
    if isinstance(labels, dict):
        guid = str(labels.get(label) or "").strip().strip("{}")
    if not guid:
        return {}
    bits = 0
    if stamped:
        bits |= 0x1 | 0x2
    if encrypted:
        bits |= 0x8
    prefix = f"MSIP_Label_{guid}"
    fields = {
        f"{prefix}_Enabled": "true",
        f"{prefix}_Method": "Privileged",
        f"{prefix}_Name": label,
        f"{prefix}_SetDate": when,
        f"{prefix}_ContentBits": str(bits),
        f"{prefix}_ActionId": str(uuid.uuid4()),
    }
    site = str(purview.get("site_id") or "").strip()
    if site:
        fields[f"{prefix}_SiteId"] = site
    return fields


def _apply_metadata(writer: Any, fields: dict[str, str], msip: dict[str, str]) -> None:
    info = {
        "/Title": fields["title"],
        "/Author": fields["user"],
        "/Subject": f"Switchbay classification: {fields['label']}",
        "/Creator": f"Switchbay {fields['version']}",
        "/Producer": f"Switchbay {fields['version']}",
        "/Keywords": f"classification={fields['label']}",
        "/SwitchbayLabel": fields["label"],
        "/SwitchbayWorkspace": fields["workspace"],
        "/SwitchbayUser": fields["user"],
        "/SwitchbayTimestamp": fields["timestamp"],
        "/SwitchbayVersion": fields["version"],
    }
    for key, value in msip.items():
        info["/" + key] = value
    writer.add_metadata(info)
    writer.xmp_metadata = _xmp(fields, msip)


def _load_public_key(pem: str) -> Any:
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    data = pem.encode("utf-8")
    try:
        if b"BEGIN CERTIFICATE" in data:
            key = x509.load_pem_x509_certificate(data).public_key()
        else:
            key = load_pem_public_key(data)
    except Exception as exc:  # noqa: BLE001
        raise ExportError("recipient certificate could not be read", 400) from exc
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise ExportError("recipient certificate must be an RSA key of at least 2048 bits", 400)
    return key


def _encrypt(writer: Any, spec: dict[str, str]) -> dict[str, str] | None:
    if spec["mode"] == "password":
        writer.encrypt(spec["password"], spec["password"], algorithm="AES-256")
        return None
    key = _load_public_key(spec["certificate"])
    password = secrets.token_urlsafe(32)
    writer.encrypt(password, password, algorithm="AES-256")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    wrapped = key.encrypt(
        password.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    fingerprint = hashlib.sha256(
        key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()
    return {
        "version": "1",
        "alg": "RSA-OAEP-SHA256",
        "pdf_encryption": "AES-256",
        "fingerprint": fingerprint,
        "wrapped_key": base64.b64encode(wrapped).decode("ascii"),
    }


def _label_transport(endpoint: str, transport: str) -> str:
    chosen = (transport or "").strip().lower()
    if chosen in ("http", "mcp"):
        return chosen
    if endpoint.rstrip("/").endswith("/mcp"):
        return "mcp"
    return "http"


def _apply_service(pdf: bytes, *, label: str, user: str, workspace: str, slug: str) -> bytes:
    purview = exports_policy().get("purview") or {}
    endpoint = str(purview.get("endpoint") or "").strip()
    if not endpoint:
        return pdf
    from . import admin_policy
    if not admin_policy.egress_allowed(endpoint):
        raise ExportError("labeling endpoint is not on the egress allowlist", 502)
    labels = purview.get("labels") if isinstance(purview.get("labels"), dict) else {}
    label_id = str((labels or {}).get(label) or "").strip().strip("{}")
    site = str(purview.get("site_id") or "").strip()
    transport = _label_transport(endpoint, str(purview.get("transport") or ""))
    if transport == "mcp":
        return _label_mcp(endpoint, pdf, label=label, label_id=label_id, site=site, slug=slug, source_id=str(purview.get("source_id") or ""))
    return _label_http(endpoint, pdf, label=label, label_id=label_id, site=site, user=user, workspace=workspace)


def _header(value: str) -> str:
    return (value or "").encode("latin-1", "replace").decode("latin-1")


def _label_http(endpoint: str, pdf: bytes, *, label: str, label_id: str, site: str, user: str, workspace: str) -> bytes:
    import urllib.error
    import urllib.request
    headers = {
        "Content-Type": "application/pdf",
        "Accept": "application/pdf",
        "X-Switchbay-Label": _header(label),
        "X-Switchbay-User": _header(user),
        "X-Switchbay-Workspace": _header(workspace),
        "X-Switchbay-Version": _header(__version__),
    }
    if label_id:
        headers["X-Switchbay-Label-Id"] = _header(label_id)
    if site:
        headers["X-Switchbay-Site-Id"] = _header(site)
    req = urllib.request.Request(endpoint, data=pdf, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_LABEL_TIMEOUT_S) as resp:  # noqa: S310
            body = resp.read()
            code = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raise ExportError(f"labeling endpoint returned HTTP {exc.code}", 502) from exc
    except Exception as exc:  # noqa: BLE001
        raise ExportError("labeling endpoint is unreachable", 502) from exc
    if code < 200 or code >= 300 or not body.startswith(b"%PDF"):
        raise ExportError("labeling endpoint did not return a PDF", 502)
    return body


def _label_mcp(endpoint: str, pdf: bytes, *, label: str, label_id: str, site: str, slug: str, source_id: str) -> bytes:
    from .federation.adapters import HttpMcpTransport
    from .federation import oauth
    token = oauth.load_token(source_id) if source_id else ""
    try:
        result = HttpMcpTransport(endpoint, token).call("apply_sensitivity_label", {
            "label": label,
            "label_id": label_id,
            "site_id": site,
            "filename": f"{slug}.pdf",
            "pdf_base64": base64.b64encode(pdf).decode("ascii"),
        })
    except Exception as exc:  # noqa: BLE001
        raise ExportError("labeling endpoint is unreachable", 502) from exc
    raw = ""
    if isinstance(result, dict):
        raw = str(result.get("pdf_base64") or result.get("pdf") or "")
    try:
        data = base64.b64decode(raw) if raw else b""
    except Exception as exc:  # noqa: BLE001
        raise ExportError("labeling endpoint did not return a PDF", 502) from exc
    if not data.startswith(b"%PDF"):
        raise ExportError("labeling endpoint did not return a PDF", 502)
    return data


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    try:
        partial.write_bytes(data)
        os.replace(partial, path)
    finally:
        if partial.is_file():
            partial.unlink()


def _show_path(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def finish(workspace: Path, decision: dict[str, Any], pdf: bytes) -> dict[str, Any]:
    """Stamp, label, and write ``pdf``. ``decision`` is prepare's body."""
    label = str(decision.get("label") or "public")
    sources = list(decision.get("sources") or [])
    dest = Path(str(decision.get("destination") or ""))
    klass = str(decision.get("destination_class") or "inside")
    try:
        data, encryption, purview, wrap = _produce(workspace, decision, pdf)
    except ExportError as exc:
        _refuse(workspace, str(exc), label=label, sources=sources, destination_class=klass)
        return _err(str(exc), exc.status)
    wrap_path = ""
    try:
        _write_bytes(dest, data)
        if wrap is not None:
            from .federation import secure
            sidecar = Path(str(dest) + ".wrap.json")
            secure.owner_write(sidecar, json.dumps(wrap, indent=2) + "\n")
            wrap_path = _show_path(workspace, sidecar)
        digest = hashlib.sha256(data).hexdigest()
        audit.record(
            workspace, "export",
            label=label, sources=sources, destination_class=klass,
            sha256=digest, user=_user(), slug=str(decision.get("slug") or ""),
            path=str(dest),
        )
    except Exception as exc:  # noqa: BLE001
        if dest.is_file():
            dest.unlink()
        sidecar = Path(str(dest) + ".wrap.json")
        if sidecar.is_file():
            sidecar.unlink()
        _refuse(workspace, "export could not be written", label=label, sources=sources, destination_class=klass)
        return _err(f"export could not be written: {exc}", 500)
    body = {
        "ok": True,
        "path": _show_path(workspace, dest),
        "bytes": len(data),
        "label": label,
        "stamped": bool(decision.get("stamp")),
        "sha256": digest,
        "destination_class": klass,
        "encryption": encryption,
        "purview": purview,
    }
    if wrap_path:
        body["wrap_path"] = wrap_path
    return {"status": 200, "body": body}


def _produce(workspace: Path, decision: dict[str, Any], pdf: bytes) -> tuple[bytes, str, str, dict[str, str] | None]:
    from pypdf import PdfReader, PdfWriter
    label = str(decision.get("label") or "public")
    try:
        reader = PdfReader(io.BytesIO(pdf))
        writer = PdfWriter()
        writer.append(reader)
    except Exception as exc:  # noqa: BLE001
        raise ExportError("PDF rendering did not produce a PDF", 500) from exc
    if not writer.pages:
        raise ExportError("PDF rendering did not produce a PDF", 500)
    stamped = bool(decision.get("stamp"))
    if stamped:
        _stamp(writer, label)
    when = _now()
    user = _user()
    fields = {
        "title": str(decision.get("title") or decision.get("slug") or "slideshow"),
        "label": label,
        "workspace": str(workspace.resolve()),
        "user": user,
        "timestamp": when,
        "version": __version__,
    }
    endpoint = str((exports_policy().get("purview") or {}).get("endpoint") or "").strip()
    spec = None if endpoint else decision.get("encrypt")
    if not isinstance(spec, dict):
        spec = None
    encrypted = bool(spec)
    msip = _msip(label, stamped=stamped, encrypted=encrypted, when=when)
    _apply_metadata(writer, fields, msip)
    wrap = _encrypt(writer, spec) if spec else None
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    purview = "metadata" if msip else ""
    if endpoint:
        # The service returns the bytes that are stored. Local encryption
        # is not applied on top of that; protection is the service's.
        data = _apply_service(
            data, label=label, user=user,
            workspace=str(workspace.resolve()),
            slug=str(decision.get("slug") or ""),
        )
        purview = "endpoint"
        wrap = None
        return data, "", purview, None
    encrypted_name = str(spec.get("mode") or "") if spec else ""
    return data, encrypted_name, purview, wrap
