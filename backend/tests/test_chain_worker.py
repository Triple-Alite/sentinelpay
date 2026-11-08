import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.chain_worker import EscrowChainWorker


@pytest.fixture
def sample_payment():
    return {
        "id": uuid.uuid4(),
        "reference": "pay_123",
        "description": "Secure contract payment",
        "amount": "1.5",
        "currency": "ETH",
        "token_address": None,
        "chain_id": 31337,
        "reference_hash": "0x" + "11" * 32,
        "onchain_payment_id": "0x" + "22" * 32,
        "expires_at": datetime.now(UTC) + timedelta(minutes=60),
        "status": "APPROVED",
        "onchain_state": "APPROVED",
    }


def test_release_authorization_uses_eip712_and_authorizer_key(sample_payment):
    private_key = "0x" + "11" * 32
    worker = EscrowChainWorker(authorizer_private_key=private_key)

    auth = worker.build_release_authorization(
        payment_id=sample_payment["onchain_payment_id"],
        reference_hash=sample_payment["reference_hash"],
        merchant="0x1111111111111111111111111111111111111111",
        customer="0x2222222222222222222222222222222222222222",
        token_address="0x0000000000000000000000000000000000000000",
        amount=sample_payment["amount"],
        decision="ALLOW",
        expires_at=int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
        chain_id=31337,
        contract_address="0x3333333333333333333333333333333333333333",
        nonce=7,
    )

    assert auth["decision"] == "ALLOW"
    assert auth["signature"]
    assert auth["nonce"] == 7
    assert auth["authorization_type"] == "ReleaseAuthorization"
    assert auth["message"]["paymentId"] == sample_payment["onchain_payment_id"]


def test_release_authorization_rejected_for_non_approved_decision(sample_payment):
    worker = EscrowChainWorker(authorizer_private_key="0x" + "11" * 32)

    with pytest.raises(ValueError, match="approved"):
        worker.build_release_authorization(
            payment_id=sample_payment["onchain_payment_id"],
            reference_hash=sample_payment["reference_hash"],
            merchant="0x1111111111111111111111111111111111111111",
            customer="0x2222222222222222222222222222222222222222",
            token_address="0x0000000000000000000000000000000000000000",
            amount=sample_payment["amount"],
            decision="REVIEW",
            expires_at=int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
            chain_id=31337,
            contract_address="0x3333333333333333333333333333333333333333",
            nonce=8,
        )


@pytest.mark.asyncio
async def test_deposited_payment_is_assessed_and_transaction_is_persisted(monkeypatch):
    worker = EscrowChainWorker(authorizer_private_key="0x" + "11" * 32)
    settings = SimpleNamespace(
        evm_rpc_url="http://localhost:8545",
        escrow_contract_address="0x3333333333333333333333333333333333333333",
        evm_chain_id=31337,
    )
    monkeypatch.setattr("app.chain_worker.get_settings", lambda: settings)
    monkeypatch.setattr(
        worker,
        "_js_assess_payment",
        lambda **_: {
            "alreadyAssessed": False,
            "state": 3,
            "decision": 0,
            "transactionHash": "0x" + "a" * 64,
            "blockNumber": 12,
            "blockHash": "0x" + "b" * 64,
        },
    )

    class FakeSession:
        def __init__(self):
            self.added = []
            self.committed = False

        def add(self, value):
            self.added.append(value)

        async def commit(self):
            self.committed = True

    payment = SimpleNamespace(
        id=uuid.uuid4(),
        reference="pay_assessment",
        amount="1.0",
        onchain_payment_id="0x" + "22" * 32,
        onchain_state="DEPOSITED",
        status="RISK_ASSESSMENT",
    )
    session = FakeSession()

    await worker._assess_deposited_payment(payment, session)

    assert payment.onchain_state == "APPROVED"
    assert payment.status == "APPROVED"
    assert session.committed
    assert len(session.added) == 1
    assert session.added[0].operation == "ASSESS"
    assert session.added[0].transaction_hash == "0x" + "a" * 64
