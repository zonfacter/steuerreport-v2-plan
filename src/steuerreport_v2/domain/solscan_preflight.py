from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import csv
import httpx
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steuerreport_v2.contracts.solscan import (
    SolanaRpcProbeRequest,
    SolanaRpcProbeResult,
    SolanaRpcSignatureProbe,
    SolscanBlockpitMissingSignature,
    SolscanCoverageCheckpoint,
    SolscanEvidenceTraceReport,
    SolscanEvidenceTraceStep,
    SolscanFileCoverage,
    SolscanMissingSignatureSummary,
    SolscanRpcEvidenceSummary,
    SolscanTokenMovementSummary,
    SolscanTokenPreflightReport,
)
from steuerreport_v2.paths import PROJECT_ROOT, USERTRANSFER_ROOT


DEFAULT_SOLSCAN_FILE = (
    USERTRANSFER_ROOT
    / "legacy_daten"
    / "Steuer-2022"
    / "export-solscan.csv"
)
DEFAULT_BLOCKPIT_SOLANA_FILE = (
    USERTRANSFER_ROOT
    / "blockpit"
    / "blockpit 09052026 Transactions.csv"
)
DEFAULT_SOLANA_WALLET = private_value('primary_solana_wallet', '')
DEFAULT_IOT_TOKEN_ADDRESS = "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns"
DEFAULT_RPC_EVIDENCE_ARTIFACT = (
    PROJECT_ROOT
    / "var"
    / "staging_audits"
    / "solscan_iot_rpc_probe_all_verified_2026-05-23.json"
)
DEFAULT_HELIUM_REWARD_EVIDENCE_ARTIFACT = (
    PROJECT_ROOT
    / "var"
    / "staging_audits"
    / "helium_solana_reward_evidence_wbr_20260619_2140_combined.json"
)


class SolscanPreflightService:
    def helium_reward_evidence(
        self,
        *,
        artifact_path: str = str(DEFAULT_HELIUM_REWARD_EVIDENCE_ARTIFACT),
    ) -> dict[str, object]:
        path = Path(artifact_path)
        if not path.exists():
            return {
                "status": "missing",
                "artifact_path": str(path),
                "target_changed": False,
                "import_effect": "none",
                "summary": {
                    "reward_rows": 0,
                    "reward_totals": {},
                },
                "rows": [],
                "methodology": (
                    "Read-only Helium/Solana Reward-Evidence. Artefakt fehlt; "
                    "es wurden keine Steuerdaten geschrieben."
                ),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "status": "failed",
                "artifact_path": str(path),
                "target_changed": False,
                "import_effect": "none",
                "error": f"{type(exc).__name__}: {exc}",
                "summary": {
                    "reward_rows": 0,
                    "reward_totals": {},
                },
                "rows": [],
                "methodology": (
                    "Read-only Helium/Solana Reward-Evidence. Artefakt konnte "
                    "nicht gelesen werden; es wurden keine Steuerdaten geschrieben."
                ),
            }
        summary = payload.get("summary") if isinstance(payload, dict) else {}
        rows = payload.get("rows") if isinstance(payload, dict) else []
        return {
            "status": "verified" if isinstance(summary, dict) and summary.get("reward_rows") else "empty",
            "artifact_path": str(path),
            "target_changed": False,
            "import_effect": "none",
            "summary": summary if isinstance(summary, dict) else {},
            "rows": rows if isinstance(rows, list) else [],
            "methodology": (
                payload.get("methodology")
                if isinstance(payload, dict) and isinstance(payload.get("methodology"), str)
                else (
                    "Read-only Helium/Solana Reward-Evidence aus RPC-Artefakt. "
                    "Keine Raw-Objects, Canonical Events, Tax-Lines oder "
                    "Portfolio-Bestaende werden geschrieben."
                )
            ),
        }

    def inspect_token(
        self,
        *,
        file_path: str = str(DEFAULT_SOLSCAN_FILE),
        blockpit_file_path: str = str(DEFAULT_BLOCKPIT_SOLANA_FILE),
        wallet: str = DEFAULT_SOLANA_WALLET,
        asset: str = "IOT",
        token_address: str = DEFAULT_IOT_TOKEN_ADDRESS,
        max_year: int | None = 2024,
        max_missing: int = 50,
        rpc_evidence_path: str | None = str(DEFAULT_RPC_EVIDENCE_ARTIFACT),
    ) -> SolscanTokenPreflightReport:
        solscan_movements = self._solscan_movements(
            Path(file_path),
            wallet=wallet,
            asset=asset,
            token_address=token_address,
            max_year=max_year,
        )
        blockpit_movements = self._blockpit_movements(
            Path(blockpit_file_path),
            asset=asset,
            max_year=max_year,
        )
        solscan_by_signature = self._sum_by_signature(solscan_movements)
        blockpit_by_signature = self._sum_by_signature(blockpit_movements)
        common = set(solscan_by_signature) & set(blockpit_by_signature)
        blockpit_missing = sorted(set(blockpit_by_signature) - set(solscan_by_signature))
        solscan_extra = sorted(set(solscan_by_signature) - set(blockpit_by_signature))
        matched_delta = sum(
            (solscan_by_signature[key] - blockpit_by_signature[key] for key in common),
            Decimal("0"),
        )
        return SolscanTokenPreflightReport(
            file_path=str(Path(file_path)),
            blockpit_file_path=str(Path(blockpit_file_path)),
            wallet=wallet,
            asset=asset.upper(),
            token_address=token_address,
            max_year=max_year,
            file_coverage=self._file_coverage(
                Path(file_path),
                token_address=token_address,
                max_year=max_year,
            ),
            solscan=self._summary(solscan_movements),
            blockpit=self._summary(blockpit_movements),
            matched_signatures=len(common),
            blockpit_missing_signatures=len(blockpit_missing),
            solscan_extra_signatures=len(solscan_extra),
            matched_quantity_delta=matched_delta,
            missing_summary=self._missing_summary(blockpit_missing, blockpit_movements),
            missing_blockpit_signatures=[
                self._missing_signature_row(signature, blockpit_movements)
                for signature in blockpit_missing[: max(max_missing, 0)]
            ],
            coverage_checkpoints=self._coverage_checkpoints(
                blockpit_movements,
                solscan_movements,
                cutoffs=[
                    datetime(2024, 2, 19, 8, 28, 0),
                    datetime(2024, 2, 23, 21, 1, 15),
                ],
            ),
            rpc_evidence=self._rpc_evidence_summary(
                Path(rpc_evidence_path) if rpc_evidence_path else None,
                expected_missing_count=len(blockpit_missing),
            ),
            target_changed=False,
        )

    def evidence_trace(
        self,
        *,
        file_path: str = str(DEFAULT_SOLSCAN_FILE),
        blockpit_file_path: str = str(DEFAULT_BLOCKPIT_SOLANA_FILE),
        wallet: str = DEFAULT_SOLANA_WALLET,
        asset: str = "IOT",
        token_address: str = DEFAULT_IOT_TOKEN_ADDRESS,
        max_year: int | None = 2024,
        rpc_evidence_path: str | None = str(DEFAULT_RPC_EVIDENCE_ARTIFACT),
    ) -> SolscanEvidenceTraceReport:
        preflight = self.inspect_token(
            file_path=file_path,
            blockpit_file_path=blockpit_file_path,
            wallet=wallet,
            asset=asset,
            token_address=token_address,
            max_year=max_year,
            rpc_evidence_path=rpc_evidence_path,
        )
        rpc = preflight.rpc_evidence
        solscan_available = Path(file_path).is_file()
        blockpit_available = Path(blockpit_file_path).is_file()
        status = "needs_evidence"
        if not solscan_available or not blockpit_available:
            status = "source_missing"
        elif preflight.blockpit_missing_signatures == 0:
            status = "covered"
        elif rpc.status == "verified" and rpc.quantity_delta_sum == 0:
            status = "rpc_verified"
        elif rpc.status == "partial":
            status = "partial"
        elif rpc.status in {"missing", "disabled"}:
            status = "missing_rpc_evidence"

        evidence_refs = [
            preflight.file_path,
            preflight.blockpit_file_path,
            "/api/v1/import/solscan/token-preflight",
        ]
        if rpc.artifact_path:
            evidence_refs.append(rpc.artifact_path)
        evidence_refs.append("/api/v1/import/solscan/evidence-trace")

        return SolscanEvidenceTraceReport(
            asset=preflight.asset,
            wallet=preflight.wallet,
            token_address=preflight.token_address,
            max_year=preflight.max_year,
            status=status,
            target_changed=False,
            import_effect="none",
            missing_signatures=preflight.blockpit_missing_signatures,
            verified_signatures=rpc.verified,
            quantity_delta_sum=rpc.quantity_delta_sum,
            preflight=preflight,
            trace_steps=[
                SolscanEvidenceTraceStep(
                    step_id="solscan_csv_coverage",
                    label="Solscan CSV Coverage",
                    status=(
                        "missing"
                        if not solscan_available
                        else "covered"
                        if preflight.blockpit_missing_signatures == 0
                        else "gap_detected"
                    ),
                    evidence_ref=preflight.file_path,
                    note=(
                        "Vergleicht Solscan-CSV und Blockpit-Export je Signatur "
                        "und Menge, ohne Rohdaten zu importieren."
                    ),
                ),
                SolscanEvidenceTraceStep(
                    step_id="blockpit_source_export",
                    label="Blockpit Referenzexport",
                    status="available" if blockpit_available else "missing",
                    evidence_ref=preflight.blockpit_file_path,
                    note=(
                        "Dient als steuerlicher Referenzsatz fuer fehlende "
                        "Solscan-Signaturen und FIFO-Herkunft."
                    ),
                ),
                SolscanEvidenceTraceStep(
                    step_id="rpc_artifact",
                    label="Solana RPC Evidence",
                    status=rpc.status,
                    evidence_ref=rpc.artifact_path,
                    note=(
                        "Belegt fehlende Signaturen per getTransaction gegen "
                        "Wallet-Delta; wird nicht als zweite Ledgerquelle importiert."
                    ),
                ),
                SolscanEvidenceTraceStep(
                    step_id="review_suggestion",
                    label="Review-Entscheidungsvorschlag",
                    status="available" if status == "rpc_verified" else "waiting",
                    evidence_ref="/api/v1/review/decision-suggestions",
                    note=(
                        "Bei vollstaendig verifizierter RPC-Evidence kann die "
                        "Luecke als Beleg akzeptiert werden; Importeffekt bleibt none."
                    ),
                ),
            ],
            evidence_refs=evidence_refs,
            review_scope="solscan_iot:blockpit_missing_signatures",
            review_suggestion_id=(
                "solscan_iot_missing_signatures_rpc_verified"
                if status == "rpc_verified"
                else None
            ),
            methodology=(
                "Read-only Solscan-Evidence-Trace: Der Report verbindet "
                "Solscan-CSV, Blockpit-Referenzexport und optionales RPC-Artefakt "
                "zu einer pruefbaren Belegspur. Er erzeugt keine Raw-Objects, "
                "Canonical Events, Tax-Lines, Review-Entscheidungen oder "
                "Portfolio-Bestaende."
            ),
        )

    def probe_missing_signatures_rpc(
        self,
        request: SolanaRpcProbeRequest,
    ) -> SolanaRpcProbeResult:
        report = self.inspect_token(
            file_path=request.file_path,
            blockpit_file_path=request.blockpit_file_path,
            wallet=request.wallet,
            asset=request.asset,
            token_address=request.token_address,
            max_year=request.max_year,
            max_missing=1000,
        )
        expected_by_signature = {
            item.signature: item
            for item in report.missing_blockpit_signatures
        }
        requested = request.signatures or list(expected_by_signature)
        selected = [
            signature for signature in requested if signature in expected_by_signature
        ][: max(0, min(request.max_requests, 50))]
        jobs: list[SolanaRpcSignatureProbe] = []
        verified = 0
        failed = 0
        rate_limited = 0
        with httpx.Client(timeout=max(3, min(request.timeout_seconds, 60))) as client:
            delay_seconds = max(Decimal("0"), min(request.delay_seconds, Decimal("10")))
            for index, signature in enumerate(selected):
                if index > 0 and delay_seconds > 0:
                    time.sleep(float(delay_seconds))
                job = self._probe_signature_rpc(
                    client=client,
                    rpc_url=request.rpc_url,
                    signature=signature,
                    wallet=request.wallet,
                    token_address=request.token_address,
                    expected=expected_by_signature[signature],
                )
                jobs.append(job)
                if job.status == "verified":
                    verified += 1
                elif job.status == "rate_limited":
                    rate_limited += 1
                else:
                    failed += 1
        return SolanaRpcProbeResult(
            requested_signatures=len(requested),
            attempted=len(jobs),
            verified=verified,
            failed=failed,
            rate_limited=rate_limited,
            target_changed=False,
            jobs=jobs,
        )

    def _probe_signature_rpc(
        self,
        *,
        client: httpx.Client,
        rpc_url: str,
        signature: str,
        wallet: str,
        token_address: str,
        expected: SolscanBlockpitMissingSignature,
    ) -> SolanaRpcSignatureProbe:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }
        try:
            response = client.post(rpc_url, json=payload)
        except httpx.HTTPError as exc:
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="failed",
                expected_quantity=expected.quantity,
                label=expected.label,
                reason=str(exc),
            )
        if response.status_code == 429:
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="rate_limited",
                expected_quantity=expected.quantity,
                label=expected.label,
                reason="rpc_http_429",
            )
        if response.status_code >= 400:
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="failed",
                expected_quantity=expected.quantity,
                label=expected.label,
                reason=f"rpc_http_{response.status_code}",
            )
        data = response.json()
        if data.get("error"):
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="failed",
                expected_quantity=expected.quantity,
                label=expected.label,
                reason=str(data["error"]),
            )
        result = data.get("result")
        if not result:
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="not_found",
                expected_quantity=expected.quantity,
                label=expected.label,
                reason="rpc_result_null",
            )
        meta = result.get("meta") or {}
        if meta.get("err") is not None:
            return SolanaRpcSignatureProbe(
                signature=signature,
                status="failed",
                expected_quantity=expected.quantity,
                slot=result.get("slot"),
                block_time=self._block_time(result.get("blockTime")),
                label=expected.label,
                reason=f"transaction_err:{meta.get('err')}",
            )
        wallet_delta = self._wallet_token_delta(
            pre=meta.get("preTokenBalances") or [],
            post=meta.get("postTokenBalances") or [],
            wallet=wallet,
            token_address=token_address,
        )
        quantity_delta = (
            wallet_delta - expected.quantity if wallet_delta is not None else None
        )
        return SolanaRpcSignatureProbe(
            signature=signature,
            status="verified" if quantity_delta == 0 else "quantity_mismatch",
            expected_quantity=expected.quantity,
            wallet_delta_quantity=wallet_delta,
            quantity_delta=quantity_delta,
            block_time=self._block_time(result.get("blockTime")),
            slot=result.get("slot"),
            label=expected.label,
            reason=None if quantity_delta == 0 else "wallet_delta_differs_from_blockpit",
        )

    def _wallet_token_delta(
        self,
        *,
        pre: list[dict],
        post: list[dict],
        wallet: str,
        token_address: str,
    ) -> Decimal | None:
        pre_quantity = self._token_balance_for_owner(pre, wallet, token_address)
        post_quantity = self._token_balance_for_owner(post, wallet, token_address)
        if pre_quantity is None and post_quantity is None:
            return None
        return (post_quantity or Decimal("0")) - (pre_quantity or Decimal("0"))

    def _token_balance_for_owner(
        self,
        balances: list[dict],
        wallet: str,
        token_address: str,
    ) -> Decimal | None:
        total: Decimal | None = None
        for balance in balances:
            if balance.get("owner") != wallet or balance.get("mint") != token_address:
                continue
            amount = self._raw_token_amount(balance)
            total = amount if total is None else total + amount
        return total

    def _raw_token_amount(self, balance: dict) -> Decimal:
        token_amount = balance.get("uiTokenAmount") or {}
        raw = Decimal(str(token_amount.get("amount") or "0"))
        decimals = int(token_amount.get("decimals") or 0)
        return raw / (Decimal(10) ** decimals)

    def _block_time(self, value: int | None) -> str | None:
        if value is None:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None).isoformat()

    def _solscan_movements(
        self,
        path: Path,
        *,
        wallet: str,
        asset: str,
        token_address: str,
        max_year: int | None,
    ) -> list[dict[str, object]]:
        movements: list[dict[str, object]] = []
        if not path.is_file():
            return movements
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("TokenAddress") or "") != token_address:
                    continue
                if wallet not in {row.get("From"), row.get("To")}:
                    continue
                event_time = datetime.fromtimestamp(
                    int(str(row.get("Time") or "0")),
                    tz=timezone.utc,
                ).replace(tzinfo=None)
                if max_year is not None and event_time.year > max_year:
                    continue
                quantity = self._decimal(row.get("Amount")) / (
                    Decimal(10) ** int(str(row.get("Decimals") or "0"))
                )
                if row.get("From") == wallet:
                    quantity = -quantity
                movements.append(
                    {
                        "signature": str(row.get("Signature") or ""),
                        "event_time": event_time,
                        "label": "TRANSFER",
                        "quantity": quantity,
                        "asset": asset.upper(),
                    }
                )
        return movements

    def _file_coverage(
        self,
        path: Path,
        *,
        token_address: str,
        max_year: int | None,
    ) -> SolscanFileCoverage:
        all_times: list[datetime] = []
        token_times: list[datetime] = []
        if not path.is_file():
            return SolscanFileCoverage()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                event_time = datetime.fromtimestamp(
                    int(str(row.get("Time") or "0")),
                    tz=timezone.utc,
                ).replace(tzinfo=None)
                if max_year is not None and event_time.year > max_year:
                    continue
                all_times.append(event_time)
                if str(row.get("TokenAddress") or "") == token_address:
                    token_times.append(event_time)
        return SolscanFileCoverage(
            first_event_at=min(all_times).isoformat() if all_times else None,
            last_event_at=max(all_times).isoformat() if all_times else None,
            first_token_event_at=min(token_times).isoformat() if token_times else None,
            last_token_event_at=max(token_times).isoformat() if token_times else None,
        )

    def _blockpit_movements(
        self,
        path: Path,
        *,
        asset: str,
        max_year: int | None,
    ) -> list[dict[str, object]]:
        movements: list[dict[str, object]] = []
        if not path.is_file():
            return movements
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                if row.get("Integration Name") != "Solana":
                    continue
                event_time = datetime.strptime(
                    str(row.get("Date (UTC)") or ""),
                    "%d.%m.%Y %H:%M:%S",
                )
                if max_year is not None and event_time.year > max_year:
                    continue
                quantity = Decimal("0")
                if str(row.get("Incoming Asset") or "").upper() == asset.upper():
                    quantity += self._decimal(row.get("Incoming Amount"))
                if str(row.get("Outgoing Asset") or "").upper() == asset.upper():
                    quantity -= self._decimal(row.get("Outgoing Amount"))
                if quantity == 0:
                    continue
                movements.append(
                    {
                        "signature": str(row.get("Trx. ID (optional)") or ""),
                        "event_time": event_time,
                        "label": str(row.get("Label") or ""),
                        "quantity": quantity,
                        "asset": asset.upper(),
                    }
                )
        return movements

    def _sum_by_signature(
        self,
        movements: list[dict[str, object]],
    ) -> dict[str, Decimal]:
        grouped: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for movement in movements:
            grouped[str(movement["signature"])] += movement["quantity"]  # type: ignore[operator]
        return dict(grouped)

    def _summary(
        self,
        movements: list[dict[str, object]],
    ) -> SolscanTokenMovementSummary:
        by_signature = self._sum_by_signature(movements)
        incoming = sum(
            (movement["quantity"] for movement in movements if movement["quantity"] > 0),
            Decimal("0"),
        )
        outgoing = sum(
            (-movement["quantity"] for movement in movements if movement["quantity"] < 0),
            Decimal("0"),
        )
        return SolscanTokenMovementSummary(
            rows=len(movements),
            signatures=len(by_signature),
            incoming_quantity=incoming,
            outgoing_quantity=outgoing,
            net_quantity=incoming - outgoing,
        )

    def _missing_signature_row(
        self,
        signature: str,
        movements: list[dict[str, object]],
    ) -> SolscanBlockpitMissingSignature:
        relevant = [item for item in movements if item["signature"] == signature]
        first = sorted(relevant, key=lambda item: item["event_time"])[0]
        quantity = sum((item["quantity"] for item in relevant), Decimal("0"))
        return SolscanBlockpitMissingSignature(
            signature=signature,
            event_time=first["event_time"].isoformat(),  # type: ignore[union-attr]
            label=str(first["label"]),
            quantity=quantity,
        )

    def _missing_summary(
        self,
        signatures: list[str],
        movements: list[dict[str, object]],
    ) -> list[SolscanMissingSignatureSummary]:
        grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        signature_set = set(signatures)
        for movement in movements:
            if movement["signature"] not in signature_set:
                continue
            event_time = movement["event_time"]
            period = event_time.strftime("%Y-%m")  # type: ignore[union-attr]
            grouped[(period, str(movement["label"]))].append(movement)
        result: list[SolscanMissingSignatureSummary] = []
        for (period, label), items in sorted(grouped.items()):
            result.append(
                SolscanMissingSignatureSummary(
                    period=period,
                    label=label,
                    signatures=len({str(item["signature"]) for item in items}),
                    net_quantity=sum(
                        (item["quantity"] for item in items),
                        Decimal("0"),
                    ),
                )
            )
        return result

    def _coverage_checkpoints(
        self,
        blockpit_movements: list[dict[str, object]],
        solscan_movements: list[dict[str, object]],
        *,
        cutoffs: list[datetime],
    ) -> list[SolscanCoverageCheckpoint]:
        checkpoints: list[SolscanCoverageCheckpoint] = []
        for cutoff in cutoffs:
            blockpit_net = self._net_until(blockpit_movements, cutoff)
            solscan_net = self._net_until(solscan_movements, cutoff)
            checkpoints.append(
                SolscanCoverageCheckpoint(
                    cutoff_at=cutoff.isoformat(),
                    blockpit_net_quantity=blockpit_net,
                    solscan_net_quantity=solscan_net,
                    delta_quantity=solscan_net - blockpit_net,
                )
            )
        return checkpoints

    def _rpc_evidence_summary(
        self,
        path: Path | None,
        *,
        expected_missing_count: int,
    ) -> SolscanRpcEvidenceSummary:
        if path is None:
            return SolscanRpcEvidenceSummary(status="disabled")
        if not path.exists():
            return SolscanRpcEvidenceSummary(status="missing", artifact_path=str(path))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SolscanRpcEvidenceSummary(status="failed", artifact_path=str(path))

        total = int(payload.get("jobs_total") or payload.get("requested_signatures") or 0)
        verified = int(payload.get("verified") or 0)
        failed = int(payload.get("failed") or 0)
        rate_limited = int(payload.get("rate_limited") or 0)
        quantity_delta = self._decimal(payload.get("quantity_delta_sum"))
        expected_sum = self._decimal(payload.get("expected_quantity_sum"))
        wallet_delta_sum = self._decimal(payload.get("wallet_delta_quantity_sum"))
        status = "failed"
        if (
            expected_missing_count == 0
            and total == 0
            and failed == 0
            and rate_limited == 0
        ):
            status = "verified"
        elif (
            total == expected_missing_count
            and verified == expected_missing_count
            and failed == 0
            and rate_limited == 0
            and quantity_delta == Decimal("0")
        ):
            status = "verified"
        elif verified > 0:
            status = "partial"
        return SolscanRpcEvidenceSummary(
            status=status,
            artifact_path=str(path),
            signatures_total=total,
            verified=verified,
            failed=failed,
            rate_limited=rate_limited,
            expected_quantity_sum=expected_sum,
            wallet_delta_quantity_sum=wallet_delta_sum,
            quantity_delta_sum=quantity_delta,
        )

    def _net_until(
        self,
        movements: list[dict[str, object]],
        cutoff: datetime,
    ) -> Decimal:
        return sum(
            (
                movement["quantity"]
                for movement in movements
                if movement["event_time"] <= cutoff
            ),
            Decimal("0"),
        )

    def _decimal(self, value: str | None) -> Decimal:
        try:
            return Decimal(str(value or "0").strip().replace(",", "."))
        except InvalidOperation:
            return Decimal("0")
