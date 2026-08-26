from __future__ import annotations

import io
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile


class BankCamtDocumentService:
    SUPPORTED_SUFFIXES = {".xml", ".zip"}
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024
    MAX_XML_BYTES = 20 * 1024 * 1024
    MAX_ZIP_MEMBERS = 500
    MAX_ZIP_UNCOMPRESSED_BYTES = 250 * 1024 * 1024

    @classmethod
    def extract_validated_xml(cls, filename: str, content: bytes) -> list[bytes]:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in cls.SUPPORTED_SUFFIXES:
            raise ValueError("Erlaubt sind ausschliesslich CAMT-XML- oder ZIP-Dateien.")
        if not content:
            raise ValueError("Der CAMT-Upload ist leer.")
        if len(content) > cls.MAX_UPLOAD_BYTES:
            raise ValueError("Der CAMT-Upload ueberschreitet das lokale Dateilimit.")
        if suffix == ".xml":
            cls.validate_xml(content)
            return [content]

        try:
            with ZipFile(io.BytesIO(content)) as archive:
                members = [
                    item
                    for item in archive.infolist()
                    if not item.is_dir() and Path(item.filename).suffix.lower() == ".xml"
                ]
                if not members:
                    raise ValueError("Das ZIP-Archiv enthaelt keine CAMT-XML-Datei.")
                if len(members) > cls.MAX_ZIP_MEMBERS:
                    raise ValueError("Das ZIP-Archiv enthaelt zu viele XML-Dateien.")
                if sum(item.file_size for item in members) > cls.MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise ValueError("Das entpackte ZIP-Archiv ueberschreitet das Dateilimit.")
                documents: list[bytes] = []
                for item in members:
                    if item.file_size > cls.MAX_XML_BYTES:
                        raise ValueError("Mindestens eine CAMT-XML-Datei ist zu gross.")
                    document = archive.read(item)
                    cls.validate_xml(document)
                    documents.append(document)
                return documents
        except BadZipFile as exc:
            raise ValueError("Das ZIP-Archiv ist nicht lesbar.") from exc

    @classmethod
    def validate_xml(cls, content: bytes) -> None:
        if len(content) > cls.MAX_XML_BYTES:
            raise ValueError("Die CAMT-XML-Datei ueberschreitet das Dateilimit.")
        upper = content.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise ValueError("XML-Dokumente mit DTD oder Entities werden nicht akzeptiert.")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError("Die CAMT-XML-Datei ist nicht wohlgeformt.") from exc
        if "camt.052." not in str(root.tag):
            raise ValueError("Die XML-Datei ist kein unterstuetzter CAMT.052-Kontoauszug.")
        local_names = {cls._local_name(element.tag) for element in root.iter()}
        if "BkToCstmrAcctRpt" not in local_names or "Rpt" not in local_names:
            raise ValueError("Die CAMT.052-Berichtsstruktur ist unvollstaendig.")
        if not ({"Ntry", "Bal"} & local_names):
            raise ValueError("Der CAMT.052-Bericht enthaelt weder Buchungen noch Salden.")

    @staticmethod
    def _local_name(tag: str) -> str:
        return str(tag).split("}", 1)[-1]
