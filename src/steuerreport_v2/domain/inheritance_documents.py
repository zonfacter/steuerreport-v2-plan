from __future__ import annotations

import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.divorce_inheritance import (
    InheritanceDocumentConnectorStatus,
    InheritanceDocumentEvidence,
)


class InheritanceDocumentService:
    SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
    MAX_FILE_BYTES = 50 * 1024 * 1024

    def scan(
        self,
        root: Path,
        *,
        configured_path: Path | None = None,
        reviewed_document_sha256: str | None = None,
        reviewed_evidence_ref: str | None = None,
    ) -> InheritanceDocumentConnectorStatus:
        paths = (
            sorted(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES
            )
            if root.is_dir()
            else []
        )
        configured_resolved = (
            configured_path.resolve()
            if configured_path is not None and configured_path.is_file()
            else None
        )
        if configured_resolved is not None and all(
            path.resolve() != configured_resolved for path in paths
        ):
            paths.append(configured_resolved)

        documents_by_hash: dict[str, InheritanceDocumentEvidence] = {}
        manifest: list[dict[str, object]] = []
        for path in sorted(paths, key=lambda item: str(item)):
            document_sha256 = self._file_sha256(path)
            source_kind = (
                "configured_path"
                if configured_resolved is not None and path.resolve() == configured_resolved
                else "managed_upload"
            )
            reviewed = source_kind == "configured_path" or (
                document_sha256 == reviewed_document_sha256
                and bool(reviewed_evidence_ref)
            )
            evidence = InheritanceDocumentEvidence(
                document_sha256=document_sha256,
                media_type=self.media_type(path.suffix),
                size_bytes=path.stat().st_size,
                source_kind=source_kind,
                review_status="reviewed" if reviewed else "candidate",
                evidence_ref=f"inheritance-document:sha256:{document_sha256}",
            )
            previous = documents_by_hash.get(document_sha256)
            if previous is None or evidence.review_status == "reviewed":
                documents_by_hash[document_sha256] = evidence
            manifest.append(
                {
                    "sha256": document_sha256,
                    "size_bytes": path.stat().st_size,
                    "media_type": evidence.media_type,
                    "source_kind": source_kind,
                }
            )

        documents = sorted(
            documents_by_hash.values(),
            key=lambda item: (item.review_status != "reviewed", item.document_sha256),
        )
        reviewed_documents = [
            item for item in documents if item.review_status == "reviewed"
        ]
        accepted = reviewed_documents[0] if reviewed_documents else None
        manifest_sha256 = (
            self._sha256(
                json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            if manifest
            else None
        )
        status = (
            "reviewed"
            if accepted is not None
            else "candidate_present"
            if documents
            else "missing"
        )
        note = (
            "Ein SHA-256-gebundener formaler Erbnachweis ist freigegeben. Das Original "
            "bleibt ausserhalb von API und Dossier."
            if status == "reviewed"
            else "Mindestens ein Dokument wurde hochgeladen, ist aber noch nicht als formaler Erbnachweis freigegeben."
            if status == "candidate_present"
            else "Es ist noch kein formaler Erbnachweis hinterlegt."
        )
        return InheritanceDocumentConnectorStatus(
            document_root=str(root),
            document_files_count=len(documents),
            document_manifest_sha256=manifest_sha256,
            status=status,
            review_ready=any(item.review_status == "candidate" for item in documents),
            accepted_document_sha256=(accepted.document_sha256 if accepted else None),
            accepted_evidence_ref=(
                reviewed_evidence_ref
                if accepted is not None
                and accepted.document_sha256 == reviewed_document_sha256
                and reviewed_evidence_ref
                else accepted.evidence_ref
                if accepted is not None
                else None
            ),
            documents=documents,
            note=note,
        )

    @classmethod
    def validate_upload(cls, filename: str, content: bytes) -> tuple[str, str]:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in cls.SUPPORTED_SUFFIXES:
            raise ValueError("Erlaubt sind ausschliesslich PDF-, JPEG- und PNG-Dokumente.")
        if not content:
            raise ValueError("Das Dokument ist leer.")
        if len(content) > cls.MAX_FILE_BYTES:
            raise ValueError("Das Dokument ueberschreitet das lokale Dateilimit.")
        media_type = cls.media_type(suffix)
        valid_signature = (
            media_type == "application/pdf" and content.startswith(b"%PDF-")
        ) or (
            media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
        ) or (
            media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
        )
        if not valid_signature:
            raise ValueError("Dateiendung und Dateisignatur stimmen nicht ueberein.")
        return suffix, media_type

    @staticmethod
    def media_type(suffix: str) -> str:
        return {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }[suffix.lower()]

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
