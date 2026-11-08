from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.api.ai import _score_and_explain
from app.config import get_settings
from app.database import SessionLocal
from app.models import PaymentChainTransaction, PaymentRequest
from app.schemas import RiskAssessmentRequest
from sqlalchemy import select

logger = logging.getLogger(__name__)


class EscrowChainWorker:
    """Heuristic risk monitor and release-authorizer for escrow payments."""

    def __init__(
        self,
        *,
        authorizer_private_key: str | None = None,
        authorizer_address: str | None = None,
    ) -> None:
        settings = get_settings()
        self.authorizer_private_key = (authorizer_private_key or settings.authorizer_private_key or "").strip()
        self.authorizer_address = (authorizer_address or settings.authorizer_address or "").strip()

    @staticmethod
    def _to_int_amount(amount: Decimal | str | int | float) -> int:
        return int(Decimal(str(amount)) * Decimal("1e18"))

    @staticmethod
    def _risk_decision_from_score(score: int) -> str:
        if score >= 80:
            return "BLOCK"
        if score >= 35:
            return "REVIEW"
        return "ALLOW"

    def _js_sign_typed_data(self, *, key: str, payload: dict[str, Any]) -> str:
        if not key:
            raise ValueError("AUTHORIZER_PRIVATE_KEY is not configured")
        node_script = """
        const { ethers } = require('ethers');
        (async () => {
          const key = process.argv[1];
          const payload = JSON.parse(process.argv[2]);
          const wallet = new ethers.Wallet(key);
          const signature = await wallet.signTypedData(payload.domain, payload.types, payload.message);
          const result = { address: wallet.address, signature };
          console.log(JSON.stringify(result));
        })();
        """
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "contracts"))
        proc = subprocess.run(
            ["node", "-e", node_script, key, json.dumps(payload)],
            capture_output=True,
            text=True,
            cwd=project_root,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"Authorizer signing failed: {proc.stderr.strip() or proc.stdout.strip()}")
        output = proc.stdout.strip()
        if not output:
            raise ValueError("Authorizer signing returned no signature")
        result = json.loads(output)
        return str(result["signature"])

    def assess_risk(self, payment: Any) -> dict[str, Any]:
        amount = Decimal(str(getattr(payment, "amount", 0) or 0))
        payload = RiskAssessmentRequest(
            transaction_id=str(getattr(payment, "reference", "") or "manual-review"),
            wallet_age_days=365,
            transaction_amount=float(amount),
            transaction_frequency=1,
            failed_tx_count=0,
            historical_volume=float(amount),
            time_since_previous_tx_hours=24,
            new_wallet=False,
            known_malicious_address=False,
            suspicious_contract_interaction=False,
            amount_deviation_ratio=0.0,
            wallet_reputation_score=90,
            payment_velocity=1,
            merchant_anomaly_score=0,
        )
        score, explanations = _score_and_explain(payload)
        decision = self._risk_decision_from_score(score)
        return {
            "score": score,
            "decision": decision,
            "risk_level": "HIGH" if score >= 80 else "MEDIUM" if score >= 35 else "LOW",
            "explanations": explanations,
        }

    def _resolve_authorizer_address(self) -> str:
        if not self.authorizer_private_key:
            raise ValueError("AUTHORIZER_PRIVATE_KEY is not configured")
        address = self.authorizer_address or self._js_address_from_key(self.authorizer_private_key)
        self.authorizer_address = address
        return address

    def _js_address_from_key(self, key: str) -> str:
        node_script = """
        const { ethers } = require('ethers');
        const key = process.argv[1];
        const wallet = new ethers.Wallet(key);
        console.log(wallet.address);
        """
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "contracts"))
        proc = subprocess.run(["node", "-e", node_script, key], capture_output=True, text=True, cwd=project_root, check=False)
        if proc.returncode != 0:
            raise ValueError(f"Unable to derive authorizer address: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    def _js_assess_payment(
        self,
        *,
        key: str,
        rpc_url: str,
        contract_address: str,
        payment_id: str,
        decision: int,
        chain_id: int,
    ) -> dict[str, Any]:
        node_script = """
        const { ethers } = require('ethers');
        (async () => {
          const [key, rpcUrl, contractAddress, paymentId, decision, expectedChainId] = process.argv.slice(1);
          const provider = new ethers.JsonRpcProvider(rpcUrl);
          const network = await provider.getNetwork();
          if (network.chainId !== BigInt(expectedChainId)) throw new Error('RPC chain ID does not match configuration');
          const wallet = new ethers.Wallet(key, provider);
          const escrow = new ethers.Contract(contractAddress, [
            'function payments(bytes32) view returns (bytes32 referenceHash,address merchant,address customer,address token,uint256 amount,uint64 expiresAt,uint8 state,uint8 decision)',
                        'function assessPayment(bytes32 paymentId,uint8 decision)',
                        'function authorizer() view returns (address)'
          ], wallet);
                    const configuredAuthorizer = await escrow.authorizer();
                    if (configuredAuthorizer.toLowerCase() !== wallet.address.toLowerCase()) {
                        throw new Error('Configured signer is not the escrow authorizer');
                    }
          const current = await escrow.payments(paymentId);
          if (current.state !== 2n && current.state !== 4n) {
            console.log(JSON.stringify({ alreadyAssessed: true, state: Number(current.state), decision: Number(current.decision) }));
            return;
          }
          const transaction = await escrow.assessPayment(paymentId, Number(decision));
          const receipt = await transaction.wait();
          if (!receipt || receipt.status !== 1) throw new Error('Assessment transaction failed');
          console.log(JSON.stringify({
            alreadyAssessed: false,
            state: Number(decision) === 0 ? 3 : 4,
            decision: Number(decision),
            transactionHash: transaction.hash,
            blockNumber: receipt.blockNumber,
            blockHash: receipt.blockHash
          }));
        })().catch(error => { console.error(error); process.exitCode = 1; });
        """
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "contracts"))
        proc = subprocess.run(
            ["node", "-e", node_script, key, rpc_url, contract_address, payment_id, str(decision), str(chain_id)],
            capture_output=True,
            text=True,
            cwd=project_root,
            check=False,
            timeout=90,
        )
        if proc.returncode != 0:
            raise ValueError(f"On-chain risk assessment failed: {proc.stderr.strip() or proc.stdout.strip()}")
        output = proc.stdout.strip().splitlines()
        if not output:
            raise ValueError("On-chain risk assessment returned no result")
        result = json.loads(output[-1])
        if not isinstance(result, dict):
            raise ValueError("On-chain risk assessment returned an invalid result")
        return result

    def build_release_authorization(
        self,
        *,
        payment_id: str,
        reference_hash: str,
        merchant: str,
        customer: str,
        token_address: str,
        amount: Decimal | str | int | float,
        decision: str,
        expires_at: int,
        chain_id: int,
        contract_address: str,
        nonce: int,
    ) -> dict[str, Any]:
        normalized_decision = str(decision).upper()
        if normalized_decision != "ALLOW":
            raise ValueError("Only approved payments can receive an EIP-712 release authorization")
        if not payment_id:
            raise ValueError("payment_id is required")
        if not self.authorizer_private_key:
            raise ValueError("AUTHORIZER_PRIVATE_KEY is not configured")

        domain = {
            "name": "SentinelEscrow",
            "version": "1",
            "chainId": int(chain_id),
            "verifyingContract": contract_address,
        }
        message = {
            "paymentId": payment_id,
            "referenceHash": reference_hash,
            "merchant": merchant,
            "customer": customer,
            "token": token_address,
            "amount": str(self._to_int_amount(amount)),
            "decision": 0,
            "expiration": int(expires_at),
            "chainId": str(int(chain_id)),
            "contractAddress": contract_address,
            "nonce": str(int(nonce)),
        }
        types = {
            "ReleaseAuthorization": [
                {"name": "paymentId", "type": "bytes32"},
                {"name": "referenceHash", "type": "bytes32"},
                {"name": "merchant", "type": "address"},
                {"name": "customer", "type": "address"},
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "decision", "type": "uint8"},
                {"name": "expiration", "type": "uint64"},
                {"name": "chainId", "type": "uint256"},
                {"name": "contractAddress", "type": "address"},
                {"name": "nonce", "type": "uint256"},
            ],
        }
        payload = {"domain": domain, "types": types, "message": message}
        signature = self._js_sign_typed_data(key=self.authorizer_private_key, payload=payload)
        return {
            "authorization_type": "ReleaseAuthorization",
            "decision": normalized_decision,
            "nonce": int(nonce),
            "expires_at": int(expires_at),
            "signature": signature,
            "authorizer": self._resolve_authorizer_address(),
            "domain": domain,
            "message": message,
        }

    async def run(self, poll_interval: float = 10.0) -> None:
        while True:
            settings = get_settings()
            if self.authorizer_private_key and settings.evm_rpc_url and settings.escrow_contract_address:
                try:
                    async with SessionLocal() as db:
                        payments = await db.scalars(
                            select(PaymentRequest).where(PaymentRequest.onchain_state == "DEPOSITED")
                        )
                        for payment in payments:
                            await self._assess_deposited_payment(payment, db)
                except Exception:
                    logger.exception("Escrow assessment poll failed")
            await asyncio.sleep(poll_interval)

    async def _assess_deposited_payment(self, payment: PaymentRequest, db: Any) -> None:
        settings = get_settings()
        if payment.onchain_payment_id is None:
            return
        risk = self.assess_risk(payment)
        decision_code = {"ALLOW": 0, "REVIEW": 1, "BLOCK": 2}[risk["decision"]]
        result = await asyncio.to_thread(
            self._js_assess_payment,
            key=self.authorizer_private_key,
            rpc_url=settings.evm_rpc_url,
            contract_address=settings.escrow_contract_address,
            payment_id=payment.onchain_payment_id,
            decision=decision_code,
            chain_id=settings.evm_chain_id,
        )
        state = int(result["state"])
        decision = int(result["decision"])
        payment.onchain_state = "APPROVED" if state == 3 else "HELD"
        payment.status = "APPROVED" if decision == 0 else "HELD"
        if not result.get("alreadyAssessed") and isinstance(result.get("transactionHash"), str):
            db.add(
                PaymentChainTransaction(
                    payment_request_id=payment.id,
                    chain_id=settings.evm_chain_id,
                    operation="ASSESS",
                    transaction_hash=result["transactionHash"].lower(),
                    status="MINED",
                    block_number=int(result["blockNumber"]),
                    block_hash=str(result["blockHash"]).lower(),
                    confirmations=1,
                    confirmed_at=datetime.now(UTC),
                )
            )
        await db.commit()

    async def approve_payment(self, payment: Any, *, db: Any | None = None) -> dict[str, Any]:
        risk = self.assess_risk(payment)
        if risk["decision"] != "ALLOW":
            return {
                "payment_id": getattr(payment, "onchain_payment_id", None),
                "decision": risk["decision"],
                "status": "HELD",
                "risk": risk,
            }

        contract_address = get_settings().escrow_contract_address
        if not contract_address:
            raise ValueError("ESCROW_CONTRACT_ADDRESS is not configured")

        authorization = self.build_release_authorization(
            payment_id=str(getattr(payment, "onchain_payment_id", "") or "0x"),
            reference_hash=str(getattr(payment, "onchain_reference_hash", "") or "0x"),
            merchant=str(getattr(payment, "merchant_wallet_address", "") or "0x0000000000000000000000000000000000000000"),
            customer=str(getattr(payment, "customer_wallet_address", "") or "0x0000000000000000000000000000000000000000"),
            token_address=str(getattr(payment, "token_address", "") or "0x0000000000000000000000000000000000000000"),
            amount=getattr(payment, "amount", "0"),
            decision="ALLOW",
            expires_at=int(getattr(payment, "expires_at", datetime.now(UTC)).timestamp()),
            chain_id=get_settings().evm_chain_id,
            contract_address=contract_address,
            nonce=0,
        )
        return {
            "payment_id": getattr(payment, "onchain_payment_id", None),
            "decision": risk["decision"],
            "status": "AUTHORIZED",
            "risk": risk,
            "authorization": authorization,
        }
