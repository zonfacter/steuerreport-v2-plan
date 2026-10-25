from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.mobile_documents import MobileDocumentInboxService


PDF_CONTENT = b"%PDF-1.4\nmobile evidence\n%%EOF\n"


def _authorized_client(tmp_path, monkeypatch):
    token_file = tmp_path / "connector-setup.token"
    token_file.write_text("document-setup-token\n", encoding="utf-8")
    monkeypatch.setenv("STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE", str(token_file))
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    return (
        store,
        TestClient(create_app(store)),
        {"Authorization": "Bearer document-setup-token"},
    )


def _mobile_headers(client, setup_headers, scopes):
    pairing = client.post(
        "/api/v1/connectors/mobile/pairings",
        headers=setup_headers,
        json={
            "device_name": "Belegscanner",
            "platform": "android",
            "scopes": scopes,
        },
    ).json()["data"]
    token = client.post(
        "/api/v1/connectors/mobile/sessions",
        json={
            "pairing_id": pairing["pairing_id"],
            "pairing_code": pairing["pairing_code"],
        },
    ).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_mobile_document_upload_is_hash_bound_private_and_tax_neutral(
    tmp_path,
    monkeypatch,
):
    store, client, setup_headers = _authorized_client(tmp_path, monkeypatch)
    mobile_headers = _mobile_headers(
        client,
        setup_headers,
        ["connector:read", "document:upload"],
    )

    response = client.post(
        "/api/v1/connectors/mobile/documents",
        headers=mobile_headers,
        files={
            "file": (
                "../../Kontoauszug 2025.pdf",
                PDF_CONTENT,
                "application/pdf",
            )
        },
        data={
            "document_kind": "bank_statement",
            "source_hint": "Sparkasse",
            "note": "  Apple Pay   Abgleich  ",
            "captured_at": "2025-12-31T23:15:00+00:00",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["status"] == "ok"
    result = body["data"]
    document = result["document"]
    assert document["document_sha256"] == hashlib.sha256(PDF_CONTENT).hexdigest()
    assert document["original_filename"] == "Kontoauszug 2025.pdf"
    assert document["document_kind"] == "bank_statement"
    assert document["source_hint"] == "Sparkasse"
    assert document["note"] == "Apple Pay Abgleich"
    assert document["review_status"] == "pending_review"
    assert document["tax_effect"] == "none_pending_review"
    assert document["first_uploaded_by_session_id"]
    assert result["inbox"]["pending_review_documents"] == 1

    mobile_inventory = client.get(
        "/api/v1/connectors/mobile/documents",
        headers=mobile_headers,
    )
    assert mobile_inventory.status_code == 401

    inventory = client.get(
        "/api/v1/connectors/mobile/documents",
        headers=setup_headers,
    )
    assert inventory.status_code == 200
    assert inventory.headers["cache-control"] == "no-store"
    assert inventory.headers["x-content-type-options"] == "nosniff"
    report = inventory.json()["data"]
    assert report["total_documents"] == 1
    assert report["pending_review_documents"] == 1
    assert report["documents"][0]["document_id"] == document["document_id"]

    download = client.get(
        document["content_download_path"],
        headers=setup_headers,
    )
    mobile_download = client.get(
        document["content_download_path"],
        headers=mobile_headers,
    )
    assert download.status_code == 200
    assert download.content == PDF_CONTENT
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-sha256"] == document["document_sha256"]
    assert mobile_download.status_code == 401

    stored_files = list((tmp_path / "var/mobile_document_inbox/files").iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{document['document_sha256']}.pdf"
    assert stored_files[0].stat().st_mode & 0o777 == 0o600

    with store.connect() as con:
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert con.execute("select count(*) from balance_ledger").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 0


def test_mobile_document_duplicate_is_idempotent_and_catalog_is_aggregate_only(
    tmp_path,
    monkeypatch,
):
    _store, client, setup_headers = _authorized_client(tmp_path, monkeypatch)
    mobile_headers = _mobile_headers(
        client,
        setup_headers,
        ["document:upload"],
    )
    request = {
        "headers": mobile_headers,
        "files": {"file": ("Beleg.pdf", PDF_CONTENT, "application/pdf")},
        "data": {"document_kind": "purchase_receipt"},
    }

    first = client.post("/api/v1/connectors/mobile/documents", **request).json()
    second = client.post("/api/v1/connectors/mobile/documents", **request).json()

    assert first["status"] == "ok"
    assert second["status"] == "warning"
    assert second["warnings"][0]["code"] == "mobile_document_already_present"
    assert second["data"]["already_present"] is True
    assert second["data"]["document"]["document_id"] == first["data"]["document"][
        "document_id"
    ]
    assert second["data"]["document"]["upload_count"] == 2
    assert second["data"]["inbox"]["total_documents"] == 1
    assert second["data"]["inbox"]["total_upload_attempts"] == 2

    catalog_response = client.get("/api/v1/connectors/catalog")
    catalog = catalog_response.json()["data"]
    assert catalog["mobile_document_inbox"] == {
        "status": "review_required",
        "total_documents": 1,
        "pending_review_documents": 1,
        "reviewed_documents": 0,
        "rejected_documents": 0,
        "stored_bytes": len(PDF_CONTENT),
        "total_upload_attempts": 2,
    }
    assert "Beleg.pdf" not in catalog_response.text
    document_connector = next(
        item
        for item in catalog["connectors"]
        if item["connector_id"] == "document-scan"
    )
    assert document_connector["availability"] == "available"
    assert document_connector["connection_status"] == "configured"
    assert "ocr" not in document_connector["capabilities"]


def test_mobile_document_upload_requires_scope_and_valid_file_signature(
    tmp_path,
    monkeypatch,
):
    _store, client, setup_headers = _authorized_client(tmp_path, monkeypatch)
    read_only_headers = _mobile_headers(
        client,
        setup_headers,
        ["connector:read"],
    )

    no_auth = client.post(
        "/api/v1/connectors/mobile/documents",
        files={"file": ("Beleg.pdf", PDF_CONTENT, "application/pdf")},
    )
    wrong_scope = client.post(
        "/api/v1/connectors/mobile/documents",
        headers=read_only_headers,
        files={"file": ("Beleg.pdf", PDF_CONTENT, "application/pdf")},
    )
    invalid_signature = client.post(
        "/api/v1/connectors/mobile/documents",
        headers=setup_headers,
        files={"file": ("Beleg.pdf", b"not-a-pdf", "application/pdf")},
    )
    mismatched_media = client.post(
        "/api/v1/connectors/mobile/documents",
        headers=setup_headers,
        files={"file": ("Beleg.pdf", PDF_CONTENT, "image/png")},
    )

    assert no_auth.status_code == 401
    assert wrong_scope.status_code == 403
    assert invalid_signature.json()["status"] == "error"
    assert invalid_signature.json()["errors"][0]["code"] == "mobile_document_rejected"
    assert mismatched_media.json()["status"] == "error"


@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("scan.jpg", b"\xff\xd8\xff\xe0mobile", "image/jpeg"),
        ("scan.png", b"\x89PNG\r\n\x1a\nmobile", "image/png"),
    ],
)
def test_mobile_document_service_accepts_supported_image_signatures(
    tmp_path,
    filename,
    content,
    media_type,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = MobileDocumentInboxService(store)

    result = service.store_document(
        filename=filename,
        content=content,
        declared_media_type=media_type,
        document_kind="other",
    )

    assert result.document.media_type == media_type
    assert service.content(result.document.document_id)[1] == content


def test_mobile_document_integrity_mismatch_blocks_download(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = MobileDocumentInboxService(store)
    result = service.store_document(
        filename="evidence.pdf",
        content=PDF_CONTENT,
        declared_media_type="application/pdf",
        document_kind="other",
    )
    stored_path = next(service.files_root.iterdir())
    stored_path.write_bytes(b"%PDF-1.4\ntampered\n")

    with pytest.raises(RuntimeError, match="mobile_document_integrity_mismatch"):
        service.content(result.document.document_id)


def test_mobile_document_storage_path_cannot_escape_inbox(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = MobileDocumentInboxService(store)
    result = service.store_document(
        filename="evidence.pdf",
        content=PDF_CONTENT,
        declared_media_type="application/pdf",
        document_kind="other",
    )
    with store.connect() as con:
        con.execute(
            "update mobile_document_inbox set storage_filename = '../../outside.pdf'"
        )

    with pytest.raises(RuntimeError, match="mobile_document_storage_path_invalid"):
        service.content(result.document.document_id)


def test_mobile_document_size_limit_is_enforced(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = MobileDocumentInboxService(store)
    monkeypatch.setattr(MobileDocumentInboxService, "MAX_FILE_BYTES", 8)

    with pytest.raises(ValueError, match="25 MiB"):
        service.store_document(
            filename="too-large.pdf",
            content=b"%PDF-1234",
            declared_media_type="application/pdf",
            document_kind="other",
        )
