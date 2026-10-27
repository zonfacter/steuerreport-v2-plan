"""Private Hash-Seiten und lokales Zweiphasen-Inventar; keine Finanzschreibzugriffe."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryPage, HistoryRecord
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


# Unabhaengig von Import-/UI-Limits; Ueberschreitung bricht explizit ab.
MAX_REFERENCES = 1_000_000
MAX_PAGES = 20_000
MAX_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
DETAIL_CHUNK_SIZE = 1000
_RESOURCE_ERRNOS = frozenset({
    errno.ENOSPC, errno.EDQUOT, errno.EMFILE, errno.ENFILE,
    errno.ENOMEM, errno.EAGAIN, errno.EINTR,
})


def _fail(code="solana_inventory_invalid"):
    raise HistoryFetchError(code, resumable=False)


def _storage_error(error: OSError, code: str):
    if error.errno in _RESOURCE_ERRNOS:
        raise HistoryFetchError("solana_inventory_storage_unavailable") from None
    raise HistoryFetchError(code, resumable=False) from None


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _encode(value):
    try:
        content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                             allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        _fail()
    if len(content) > MAX_FILE_BYTES:
        _fail("solana_inventory_limit")
    return content


@contextmanager
def _directory(path: Path, *, create=False):
    """Jede Pfadkomponente per dir_fd oeffnen, niemals Symlinks folgen."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.absolute().parts[1:]:
            if part in (".", ".."):
                _fail()
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


class InventoryFiles:
    def __init__(self, store, job_id):
        self.path = HistoryStorage(store).directory(job_id) / "inventory"
        self._usage = None

    @contextmanager
    def opened(self):
        try:
            with _directory(self.path, create=True) as fd:
                if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                    _fail("solana_inventory_storage_invalid")
                if self._usage is None:
                    self._prepare(fd)
                yield fd
        except OSError as error:
            self._usage = None
            _storage_error(error, "solana_inventory_storage_invalid")

    def _prepare(self, fd):
        count, size, removed = 0, 0, False
        # Nach Prozessabbruch koennen temporaere Dateien oder die zweite Link-
        # Haelfte eines atomaren Appends uebrig sein. Nur private Tempnamen loesen.
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES
                        or stat.S_IMODE(info.st_mode) & 0o077):
                    _fail("solana_inventory_storage_invalid")
                count, size = count + 1, size + info.st_size
                if count > 2 * MAX_PAGES + 2 or size > MAX_BYTES:
                    _fail("solana_inventory_limit")
                temporary = entry.name.removeprefix(".pending-")
                if entry.name.startswith(".pending-") and len(temporary) == 32 and _hash(temporary * 2):
                    os.unlink(entry.name, dir_fd=fd)
                    removed = True
                    continue
                if not entry.name.endswith(".json") or not _hash(entry.name[:-5]):
                    _fail("solana_inventory_storage_invalid")
        if removed:
            os.fsync(fd)
        # Konservativ einschliesslich bereinigter Tempdateien fuer diesen Lauf.
        self._usage = (count, size)

    def _read(self, fd, digest):
        if not _hash(digest):
            _fail()
        try:
            handle = os.open(digest + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_FILE_BYTES):
                    _fail("solana_inventory_evidence_changed")
                content = stream.read(MAX_FILE_BYTES + 1)
        except OSError as error:
            self._usage = None
            _storage_error(error, "solana_inventory_evidence_missing")
        if len(content) > MAX_FILE_BYTES or hashlib.sha256(content).hexdigest() != digest:
            _fail("solana_inventory_evidence_changed")
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            _fail("solana_inventory_evidence_changed")
        if not isinstance(value, dict):
            _fail()
        return value

    def read(self, digest):
        with self.opened() as fd:
            return self._read(fd, digest)

    def write(self, value):
        content = _encode(value)
        digest = hashlib.sha256(content).hexdigest()
        with self.opened() as fd:
            try:
                os.stat(digest + ".json", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                self._read(fd, digest)
                return digest
            count, size = self._usage
            if count + 1 > 2 * MAX_PAGES + 2 or size + len(content) > MAX_BYTES:
                _fail("solana_inventory_limit")
            temporary = ".pending-" + uuid4().hex
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, digest + ".json", src_dir_fd=fd, dst_dir_fd=fd,
                            follow_symlinks=False)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary, dir_fd=fd)
            os.fsync(fd)
            self._read(fd, digest)
            self._usage = (count + 1, size + len(content))
        return digest


class HistoryInventory:
    def __init__(self, collector):
        self.collector = collector
        self.files = InventoryFiles(collector.store, collector.options.inventory_job_id)
        self.scope = {**collector._scope(), "rpc_provider": collector.options.rpc_provider,
                      "inventory_job_id": str(collector.options.inventory_job_id)}
        self.scope_hash = hashlib.sha256(_encode(self.scope)).hexdigest()
        # Public/custom vorsichtig, bekannte Standard-RPCs mit dokumentierten 1000.
        # https://www.helius.dev/docs/api-reference/rpc/http/getsignaturesforaddress
        # https://www.alchemy.com/docs/chains/solana/solana-api-endpoints/get-signatures-for-address
        self.page_size = 1000 if collector.options.rpc_provider in ("helius", "alchemy") else 100
        self._summary = None
        self._validated_pages: set[str] = set()

    def _blob(self, kind, **values):
        return {"version": 1, "kind": kind, "scope_hash": self.scope_hash, **values}

    def _read(self, digest, kind):
        value = self.files.read(digest)
        if (type(value.get("version")) is not int or value["version"] != 1
                or value.get("kind") != kind or value.get("scope_hash") != self.scope_hash):
            _fail()
        return value

    def _signature_items(self, payload, limit):
        items = self.collector._signature_page(payload, limit=limit)
        for item in items:
            if item.get("confirmationStatus") != "finalized":
                _fail("solana_signatures_not_finalized")
            if ("slot" in item and (type(item["slot"]) is not int or item["slot"] < 0)
                    or item.get("memo") is not None and not isinstance(item["memo"], str)
                    or item.get("err") is not None and not isinstance(item["err"], (dict, str))):
                _fail("solana_signatures_invalid")
        return items

    def _owners(self, digest):
        addresses = self._read(digest, "owners").get("addresses")
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= self.collector.MAX_ADDRESSES:
            _fail()
        if addresses[0] != {"address": self.collector.wallet_address}:
            _fail()
        try:
            for item in addresses[1:]:
                if item["program"] not in self.collector.SOLANA_TOKEN_PROGRAM_IDS:
                    _fail()
                if item != self.collector._owner_address(item["owner_account"], item["program"]):
                    _fail()
            if len({item["address"] for item in addresses}) != len(addresses):
                _fail()
        except (KeyError, TypeError):
            _fail()
        return addresses

    def _raw(self, digest, index, previous):
        page = self._read(digest, "signatures")
        if (type(page.get("index")) is not int or page["index"] != index
                or type(page.get("address_index")) is not int or page.get("previous") != previous):
            _fail()
        # _read prueft die Datei bei JEDER Nutzung erneut gegen ihren Hash.
        # Derselbe Hash braucht keine erneute Base58-/Metadatenvalidierung.
        if digest not in self._validated_pages:
            page["items"] = self._signature_items(page.get("items"), 1000)
            self._validated_pages.add(digest)
        return page

    def _detail_chunks(self, state, counts, check):
        for number, digest in enumerate(state["chunks"]):
            check()
            chunk = self._read(digest, "details")
            entries = chunk.get("entries")
            if (type(chunk.get("index")) is not int or chunk["index"] != number
                    or chunk.get("previous") != (state["chunks"][number - 1] if number else state["pages"][-1])
                    or not isinstance(entries, list) or not 1 <= len(entries) <= DETAIL_CHUNK_SIZE):
                _fail()
            for ref in entries:
                if (not isinstance(ref, list) or len(ref) != 2 or any(type(v) is not int for v in ref)
                        or not 0 <= ref[0] < len(state["pages"]) or not 0 <= ref[1] < 1000):
                    _fail()
            counts.append(len(entries))
            yield from entries

    def _manifest(self, state, addresses, check):
        pages, chunks = state["pages"], state["chunks"]
        # Nur unveraenderliche belegte Praefixe cachen, nie RPC-/Marker-Zwischenstand.
        cached = self._summary
        if (cached and type(pages) is list and type(chunks) is list
                and cached["owners"] == state["owners"]
                and cached["pages"] == pages and cached["chunks"] == chunks):
            return cached
        if (not isinstance(pages, list) or len(pages) > MAX_PAGES or not all(_hash(h) for h in pages)
                or len(set(pages)) != len(pages) or not isinstance(chunks, list)
                or len(chunks) > (MAX_REFERENCES + DETAIL_CHUNK_SIZE - 1) // DETAIL_CHUNK_SIZE
                or not all(_hash(h) for h in chunks) or len(set(chunks)) != len(chunks)):
            _fail()
        counts, unique = [], set()
        detail_refs = self._detail_chunks(state, counts, check)
        index, before, references, scan_seen = 0, None, 0, set()
        for number, digest in enumerate(pages):
            check()
            page = self._raw(digest, number, pages[number - 1] if number else state["owners"])
            if index >= len(addresses) or page.get("address_index") != index or page.get("before") != before:
                _fail()
            items = page["items"]
            signatures = {item["signature"] for item in items}
            if scan_seen & signatures:
                _fail("solana_signature_cursor_loop")
            scan_seen.update(signatures)
            if state["inventory_complete"]:
                for offset, item in enumerate(items):
                    if item["signature"] not in unique:
                        unique.add(item["signature"])
                        if next(detail_refs, None) != [number, offset]:
                            _fail()
            references += len(items)
            if references > MAX_REFERENCES:
                _fail("solana_inventory_limit")
            if not items:
                index, before, scan_seen = index + 1, None, set()
            else:
                before = items[-1]["signature"]
        if next(detail_refs, None) is not None:
            _fail()
        total = sum(counts)
        if total > references or (index != len(addresses) and chunks):
            _fail()
        summary = {"owners": state["owners"], "pages": list(pages), "chunks": list(chunks),
                   "scan_index": index, "before": before, "references": references,
                   "scan_seen": scan_seen, "counts": counts, "total": total}
        self._summary = summary
        return summary

    def _state(self, cursor, check):
        if not isinstance(cursor, dict):
            _fail("solana_cursor_invalid")
        if not cursor:
            return None, None, None
        state = deepcopy(cursor)
        try:
            if (type(state["version"]) is not int or state["version"] != 2 or state["scope"] != self.scope
                    or type(state["inventory_complete"]) is not bool):
                _fail("solana_cursor_invalid")
            addresses = self._owners(state["owners"])
            summary = self._manifest(state, addresses, check)
            for field in ("scan_index", "references_discovered", "fetch_page", "fetch_offset", "signatures_completed"):
                if type(state[field]) is not int or state[field] < 0:
                    _fail("solana_cursor_invalid")
            complete = summary["scan_index"] == len(addresses)
            if (state["scan_index"] != summary["scan_index"] or state["before"] != summary["before"]
                    or state["references_discovered"] != summary["references"]
                    or state["inventory_complete"] != complete):
                _fail("solana_cursor_invalid")
            if complete:
                if type(state["signatures_total"]) is not int or state["signatures_total"] != summary["total"]:
                    _fail("solana_cursor_invalid")
                if summary["references"] and not summary["total"]:
                    _fail("solana_cursor_invalid")
            elif state["signatures_total"] is not None or state["chunks"]:
                _fail("solana_cursor_invalid")
            position, offset = state["fetch_page"], state["fetch_offset"]
            counts = summary["counts"]
            if (position > len(counts) or (offset != 0 if position == len(counts) else offset >= counts[position])
                    or state["signatures_completed"] != sum(counts[:position]) + offset):
                _fail("solana_cursor_invalid")
        except (KeyError, TypeError, IndexError):
            _fail("solana_cursor_invalid")
        return state, addresses, summary

    def _deduplicate(self, state, check):
        # Einmalig, rein lokal und durch MAX_REFERENCES begrenzt. Keine zweite Kopie
        # der Original-Metadaten: Detail-Chunks enthalten nur [Seite, Eintrag].
        seen, entries, chunks = set(), [], []
        pages = state["pages"]

        def flush():
            if entries:
                check()
                chunks.append(self.files.write(self._blob(
                    "details", index=len(chunks), previous=chunks[-1] if chunks else pages[-1],
                    entries=entries,
                )))
                entries.clear()

        for number, digest in enumerate(pages):
            check()
            page = self._raw(digest, number, pages[number - 1] if number else state["owners"])
            for offset, item in enumerate(page["items"]):
                if item["signature"] not in seen:
                    seen.add(item["signature"])
                    entries.append([number, offset])
                    if len(entries) == DETAIL_CHUNK_SIZE:
                        flush()
        flush()
        state.update(chunks=chunks, inventory_complete=True, signatures_total=len(seen))

    def _record(self, item, address, tx, check):
        collector = self.collector
        signature = item["signature"]
        if not isinstance(tx, dict):
            raise HistoryFetchError("solana_transaction_missing")
        try:
            rows = collector._solana_transaction_rows(collector.wallet_address, signature, tx)
            transaction = tx["transaction"]
            if "signatures" in transaction and (not isinstance(transaction["signatures"], list)
                    or not transaction["signatures"] or transaction["signatures"][0] != signature):
                raise ValueError
            timestamp = datetime.fromtimestamp(tx["blockTime"], timezone.utc)
        except (RequestCancelled, RequestDeadlineExceeded):
            raise
        except Exception:
            check()
            raise HistoryFetchError("solana_transaction_incomplete") from None
        if collector.start <= timestamp <= collector.end:
            return HistoryRecord(
                identity="solana:" + signature, source="solana_rpc", rows=rows,
                raw={"source_ref": collector.target.source_ref, "wallet_address": collector.wallet_address,
                     "signature": signature, "signature_info": deepcopy(item), "transaction": deepcopy(tx),
                     "scan_address": address["address"], "address_evidence": deepcopy(address)},
            )
        return None

    def fetch_page(self, cursor, check):
        check()
        state, addresses, summary = self._state(cursor, check)
        requests = 0

        def rpc(method, params):
            nonlocal requests
            check()
            requests += 1
            try:
                return self.collector._solana_rpc(method, params, timeout_seconds=30)
            except (RequestCancelled, RequestDeadlineExceeded):
                raise
            except Exception:
                check()
                code = "solana_transaction_fetch_failed" if method == "getTransaction" else "solana_rpc_failed"
                raise HistoryFetchError(code) from None

        if state is None:
            addresses = [{"address": self.collector.wallet_address}]
            by_address = {addresses[0]["address"]: addresses[0]}
            for program in self.collector.SOLANA_TOKEN_PROGRAM_IDS:
                payload = rpc("getTokenAccountsByOwner", [
                    self.collector.wallet_address, {"programId": program},
                    {"encoding": "jsonParsed", "commitment": "finalized"},
                ])
                values = payload.get("value") if isinstance(payload, dict) else None
                if not isinstance(values, list):
                    raise HistoryFetchError("solana_owner_accounts_invalid")
                if len(values) > self.collector.MAX_ADDRESSES:
                    _fail("solana_address_limit")
                for entry in values:
                    check()
                    owned = self.collector._owner_address(entry, program)
                    previous = by_address.get(owned["address"])
                    if previous is not None and previous != owned:
                        raise HistoryFetchError("solana_owner_accounts_conflict")
                    by_address[owned["address"]] = owned
                    if len(by_address) > self.collector.MAX_ADDRESSES:
                        _fail("solana_address_limit")
            addresses = list(by_address.values())
            check()
            owner_hash = self.files.write(self._blob("owners", addresses=addresses))
            state = {"version": 2, "scope": deepcopy(self.scope), "owners": owner_hash, "pages": [], "chunks": [],
                     "scan_index": 0, "before": None, "references_discovered": 0,
                     "inventory_complete": False, "signatures_total": None,
                     "fetch_page": 0, "fetch_offset": 0, "signatures_completed": 0}
            summary = self._manifest(state, addresses, check)

        records = []
        fetch_phase = state["inventory_complete"]
        if not fetch_phase:
            if len(state["pages"]) >= MAX_PAGES:
                _fail("solana_inventory_limit")
            config = {"limit": self.page_size, "commitment": "finalized"}
            if state["before"] is not None:
                config["before"] = state["before"]
            page = self._signature_items(rpc("getSignaturesForAddress", [
                addresses[state["scan_index"]]["address"], config,
            ]), self.page_size)
            if any(item["signature"] in summary["scan_seen"] for item in page):
                _fail("solana_signature_cursor_loop")
            if state["references_discovered"] + len(page) > MAX_REFERENCES:
                _fail("solana_inventory_limit")
            check()
            digest = self.files.write(self._blob(
                "signatures", index=len(state["pages"]),
                previous=state["pages"][-1] if state["pages"] else state["owners"],
                address_index=state["scan_index"], before=state["before"], items=page,
            ))
            state["pages"].append(digest)
            state["references_discovered"] += len(page)
            if page:
                state["before"] = page[-1]["signature"]
            else:
                state["scan_index"] += 1
                state["before"] = None
            if state["scan_index"] == len(addresses):
                self._deduplicate(state, check)
            total = state["signatures_total"] or 0
            scan_seen = summary["scan_seen"] if page else set()
            scan_seen.update(item["signature"] for item in page)
            self._summary = {
                "owners": state["owners"], "pages": list(state["pages"]), "chunks": list(state["chunks"]),
                "scan_index": state["scan_index"], "before": state["before"],
                "references": state["references_discovered"],
                "scan_seen": scan_seen,
                "counts": [min(DETAIL_CHUNK_SIZE, total - i * DETAIL_CHUNK_SIZE)
                           for i in range(len(state["chunks"]))], "total": total,
            }
        else:
            pages, chunks = state["pages"], state["chunks"]
            raw_pages, detail_chunks = {}, {}
            for _ in range(self.collector.DETAILS_PER_PAGE):
                position, offset = state["fetch_page"], state["fetch_offset"]
                if position == len(chunks):
                    break
                check()
                if position not in detail_chunks:
                    detail_chunks[position] = self._read(chunks[position], "details")
                chunk = detail_chunks[position]
                ref = chunk["entries"][offset]
                if ref[0] not in raw_pages:
                    raw_pages[ref[0]] = self._raw(pages[ref[0]], ref[0],
                                                 pages[ref[0] - 1] if ref[0] else state["owners"])
                raw = raw_pages[ref[0]]
                try:
                    item = raw["items"][ref[1]]
                    address = addresses[raw["address_index"]]
                except (IndexError, KeyError, TypeError):
                    _fail()
                record = self._record(item, address, rpc("getTransaction", [item["signature"], {
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "finalized",
                }]), check)
                if record is not None:
                    records.append(record)
                state["signatures_completed"] += 1
                state["fetch_offset"] += 1
                if state["fetch_offset"] == len(chunk["entries"]):
                    state["fetch_page"], state["fetch_offset"] = position + 1, 0

        check()
        complete = state["inventory_complete"]
        total = state["signatures_total"]
        done = complete and state["signatures_completed"] == total
        return HistoryPage(
            records=records, cursor=state, done=done, requests=requests, notes=self.collector.NOTES,
            phase="Transaktionen abrufen" if fetch_phase else "Signaturen inventarisieren",
            extra={"progress": {
                "phase": "fetch" if fetch_phase else "discovery",
                "references_discovered": state["references_discovered"],
                "signatures_discovered": total, "signatures_total": total,
                "signatures_completed": state["signatures_completed"],
                "addresses_completed": state["scan_index"], "addresses_total": len(addresses),
                "inventory_complete": complete,
            }},
        )
