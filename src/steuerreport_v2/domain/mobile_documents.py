from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from steuerreport_v2.contracts.mobile_documents import (
    MobileDocumentEvidence,
    MobileDocumentInboxReport,
    MobileDocumentInboxSummary,
    MobileDocumentKind,
    MobileDocumentUploadResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.paths import PROJECT_ROOT


class MobileDocumentInboxService:
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/mobile_document_inbox"
    ARTIFACT_ROOT_ENV = "STEUERREPORT_V2_MOBILE_DOCUMENT_ROOT"
    MAX_FILE_BYTES = 25 * 1024 * 1024
    SUPPORTED_MEDIA_TYPES = ("application/pdf", "image/jpeg", "image/png")
    _MEDIA_BY_SUFFIX = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    _SUFFIX_BY_MEDIA = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }
    _DOCUMENT_KINDS = {
        "bank_statement",
        "exchange_statement",
        "purchase_receipt",
        "tax_notice",
        "inheritance_evidence",
        "portfolio_statement",
        "other",
    }
    _write_lock = RLock()

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()
        self.files_root = self.artifact_root / "files"

    def store_document(
        self,
        *,
        filename: str,
        content: bytes,
        declared_media_type: str | None,
        document_kind: MobileDocumentKind,
        source_hint: str | None = None,
        note: str | None = None,
        captured_at: datetime | None = None,
        uploaded_by_session_id: str | None = None,
        now: datetime | None = None,
    ) -> MobileDocumentUploadResult:
        uploaded_at = self._utc(now or datetime.now(timezone.utc))
        safe_filename, suffix, media_type = self._validate_upload(
            filename,
            content,
            declared_media_type,
        )
        if document_kind not in self._DOCUMENT_KINDS:
            raise ValueError("Die Dokumentart ist nicht erlaubt.")
        normalized_source_hint = self._optional_text(
            source_hint,
            max_length=120,
            field_name="Quellenhinweis",
        )
        normalized_note = self._optional_text(
            note,
            max_length=500,
            field_name="Notiz",
        )
        normalized_captured_at = self._utc(captured_at) if captured_at else None
        document_sha256 = hashlib.sha256(content).hexdigest()
        storage_filename = f"{document_sha256}{suffix}"
        storage_path = self.files_root / storage_filename
        content_restored = False
        file_created = False

        with self._write_lock:
            with self.store.connect() as con:
                existing = con.execute(
                    """
                    select document_id, storage_filename
                    from mobile_document_inbox
                    where document_sha256 = ?
                    """,
                    [document_sha256],
                ).fetchone()

            effective_storage_filename = (
                str(existing[1]) if existing is not None else storage_filename
            )
            storage_path = self._safe_storage_path(effective_storage_filename)
            if storage_path.is_file():
                if self._file_sha256(storage_path) != document_sha256:
                    raise RuntimeError("mobile_document_integrity_mismatch")
            else:
                self._atomic_private_write(storage_path, content)
                file_created = True
                content_restored = existing is not None

            if existing is not None:
                document_id = str(existing[0])
                with self.store.connect() as con:
                    con.execute(
                        """
                        update mobile_document_inbox
                        set last_uploaded_at = ?, upload_count = upload_count + 1,
                            last_uploaded_by_session_id = ?
                        where document_id = ?
                        """,
                        [uploaded_at, uploaded_by_session_id, document_id],
                    )
                already_present = True
            else:
                document_id = str(uuid4())
                try:
                    with self.store.connect() as con:
                        con.execute(
                            """
                            insert into mobile_document_inbox (
                                document_id, document_sha256, original_filename,
                                storage_filename, media_type, size_bytes,
                                document_kind, source_hint, note, captured_at,
                                first_uploaded_at, last_uploaded_at, upload_count,
                                first_uploaded_by_session_id,
                                last_uploaded_by_session_id, review_status
                            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'pending_review')
                            """,
                            [
                                document_id,
                                document_sha256,
                                safe_filename,
                                storage_filename,
                                media_type,
                                len(content),
                                document_kind,
                                normalized_source_hint,
                                normalized_note,
                                normalized_captured_at,
                                uploaded_at,
                                uploaded_at,
                                uploaded_by_session_id,
                                uploaded_by_session_id,
                            ],
                        )
                except Exception:
                    if file_created:
                        storage_path.unlink(missing_ok=True)
                    raise
                already_present = False

        document = self.document(document_id)
        return MobileDocumentUploadResult(
            document=document,
            already_present=already_present,
            content_restored=content_restored,
            inbox=self.summary(),
        )

    def document(self, document_id: str) -> MobileDocumentEvidence:
        with self.store.connect() as con:
            row = con.execute(
                self._document_select() + " where document_id = ?",
                [document_id.strip()],
            ).fetchone()
        if row is None:
            raise ValueError("mobile_document_not_found")
        return self._document_from_row(row)

    def report(self, *, limit: int = 100) -> MobileDocumentInboxReport:
        normalized_limit = max(1, min(int(limit), 500))
        summary = self.summary()
        with self.store.connect() as con:
            rows = con.execute(
                self._document_select()
                + " order by last_uploaded_at desc, document_id limit ?",
                [normalized_limit],
            ).fetchall()
        documents = [self._document_from_row(row) for row in rows]
        return MobileDocumentInboxReport(
            **summary.model_dump(),
            generated_at=datetime.now(timezone.utc),
            returned_documents=len(documents),
            max_file_bytes=self.MAX_FILE_BYTES,
            supported_media_types=list(self.SUPPORTED_MEDIA_TYPES),
            documents=documents,
            methodology=(
                "Private, SHA-256-gebundene Quarantaene-Inbox fuer mobile PDF-, JPEG- und "
                "PNG-Belege. Upload und Dublettenerkennung erzeugen keine Canonical Events, "
                "Ledger-Buchungen, FIFO-Lots, Steuerzeilen oder Review-Freigaben. OCR und "
                "fachliche Zuordnung erfolgen erst in einem getrennten Review-Schritt."
            ),
        )

    def summary(self) -> MobileDocumentInboxSummary:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*),
                       sum(case when review_status = 'pending_review' then 1 else 0 end),
                       sum(case when review_status = 'reviewed' then 1 else 0 end),
                       sum(case when review_status = 'rejected' then 1 else 0 end),
                       coalesce(sum(size_bytes), 0),
                       coalesce(sum(upload_count), 0)
                from mobile_document_inbox
                """
            ).fetchone()
        total_documents = int(row[0] or 0) if row else 0
        pending_review = int(row[1] or 0) if row else 0
        return MobileDocumentInboxSummary(
            status=(
                "review_required"
                if pending_review
                else "stored"
                if total_documents
                else "empty"
            ),
            total_documents=total_documents,
            pending_review_documents=pending_review,
            reviewed_documents=int(row[2] or 0) if row else 0,
            rejected_documents=int(row[3] or 0) if row else 0,
            stored_bytes=int(row[4] or 0) if row else 0,
            total_upload_attempts=int(row[5] or 0) if row else 0,
        )

    def content(self, document_id: str) -> tuple[MobileDocumentEvidence, bytes]:
        document = self.document(document_id)
        with self.store.connect() as con:
            row = con.execute(
                """
                select storage_filename
                from mobile_document_inbox
                where document_id = ?
                """,
                [document.document_id],
            ).fetchone()
        if row is None:
            raise ValueError("mobile_document_not_found")
        path = self._safe_storage_path(str(row[0]))
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RuntimeError("mobile_document_content_missing") from exc
        if hashlib.sha256(content).hexdigest() != document.document_sha256:
            raise RuntimeError("mobile_document_integrity_mismatch")
        return document, content

    def _default_artifact_root(self) -> Path:
        configured = os.environ.get(self.ARTIFACT_ROOT_ENV, "").strip()
        if configured:
            return Path(configured).expanduser()
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/mobile_document_inbox"

    @classmethod
    def _validate_upload(
        cls,
        filename: str,
        content: bytes,
        declared_media_type: str | None,
    ) -> tuple[str, str, str]:
        if not content:
            raise ValueError("Das Dokument ist leer.")
        if len(content) > cls.MAX_FILE_BYTES:
            raise ValueError("Das Dokument ueberschreitet das Limit von 25 MiB.")
        safe_filename = cls._safe_filename(filename)
        suffix = Path(safe_filename).suffix.lower()
        normalized_declared = (declared_media_type or "").split(";", 1)[0].strip().lower()
        if not suffix and normalized_declared in cls._SUFFIX_BY_MEDIA:
            suffix = cls._SUFFIX_BY_MEDIA[normalized_declared]
            safe_filename = f"{safe_filename or 'mobile-document'}{suffix}"
        media_type = cls._MEDIA_BY_SUFFIX.get(suffix)
        if media_type is None:
            raise ValueError("Erlaubt sind ausschliesslich PDF-, JPEG- und PNG-Dokumente.")
        if normalized_declared not in {"", "application/octet-stream", media_type}:
            raise ValueError("Dateiendung und gemeldeter Medientyp stimmen nicht ueberein.")
        valid_signature = (
            media_type == "application/pdf" and content.startswith(b"%PDF-")
        ) or (
            media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
        ) or (
            media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
        )
        if not valid_signature:
            raise ValueError("Dateiendung und Dateisignatur stimmen nicht ueberein.")
        return safe_filename, suffix, media_type

    @staticmethod
    def _safe_filename(filename: str) -> str:
        basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = "".join(character for character in basename if character.isprintable())
        cleaned = " ".join(cleaned.split()).strip(" .")
        if len(cleaned) > 180:
            suffix = Path(cleaned).suffix[:12]
            cleaned = cleaned[: 180 - len(suffix)].rstrip(" .") + suffix
        return cleaned or "mobile-document"

    @staticmethod
    def _optional_text(
        value: str | None,
        *,
        max_length: int,
        field_name: str,
    ) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"{field_name} ueberschreitet {max_length} Zeichen.")
        return normalized

    def _safe_storage_path(self, storage_filename: str) -> Path:
        root = self.files_root.resolve()
        path = (self.files_root / storage_filename).resolve()
        if path.parent != root:
            raise RuntimeError("mobile_document_storage_path_invalid")
        return path

    @staticmethod
    def _atomic_private_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.replace(path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _document_select() -> str:
        return """
            select document_id, document_sha256, original_filename, media_type,
                   size_bytes, document_kind, source_hint, note, captured_at,
                   first_uploaded_at, last_uploaded_at, upload_count,
                   first_uploaded_by_session_id, last_uploaded_by_session_id,
                   review_status
            from mobile_document_inbox
        """

    @classmethod
    def _document_from_row(cls, row: tuple[object, ...]) -> MobileDocumentEvidence:
        document_id = str(row[0])
        document_sha256 = str(row[1])
        return MobileDocumentEvidence(
            document_id=document_id,
            document_sha256=document_sha256,
            original_filename=str(row[2]),
            media_type=str(row[3]),
            size_bytes=int(row[4]),
            document_kind=str(row[5]),
            source_hint=str(row[6]) if row[6] is not None else None,
            note=str(row[7]) if row[7] is not None else None,
            captured_at=cls._utc(row[8]) if row[8] is not None else None,
            first_uploaded_at=cls._utc(row[9]),
            last_uploaded_at=cls._utc(row[10]),
            upload_count=int(row[11]),
            first_uploaded_by_session_id=(
                str(row[12]) if row[12] is not None else None
            ),
            last_uploaded_by_session_id=(
                str(row[13]) if row[13] is not None else None
            ),
            review_status=str(row[14]),
            evidence_ref=f"mobile-document-inbox:sha256:{document_sha256}",
            content_download_path=(
                f"/api/v1/connectors/mobile/documents/{document_id}/content"
            ),
        )

    @staticmethod
    def _utc(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("datetime_required")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
