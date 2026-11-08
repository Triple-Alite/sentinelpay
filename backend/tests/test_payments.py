from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api import payments as payments_api
from app.api import chain as chain_api


def registration_payload(email: str, business_name: str) -> dict[str, str]:
    return {
        "full_name": "Test Owner",
        "business_name": business_name,
        "email": email,
        "password": "Correct-Horse-42!",
        "country": "US",
    }


def payment_payload(**overrides) -> dict:
    payload = {
        "amount": "0.05",
        "currency": "ETH",
        "description": "Order 1001",
        "chain_id": 11155111,
        "expires_in_minutes": 60,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_payment_request_checkout_and_cancel(client):
    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("merchant@example.com", "Merchant One"),
    )
    created = await client.post("/api/v1/payments", json=payment_payload())
    assert created.status_code == 201
    payment = created.json()
    assert payment["status"] == "CREATED"
    assert payment["token_address"] is None
    assert payment["onchain_payment_id"].startswith("0x")
    assert len(payment["onchain_payment_id"]) == 66
    assert payment["onchain_reference_hash"].startswith("0x")
    assert len(payment["onchain_reference_hash"]) == 66
    assert payment["onchain_state"] == "NOT_CREATED"
    assert payment["checkout_url"] == f"/checkout/{payment['reference']}"

    checkout = await client.get(f"/api/v1/payments/checkout/{payment['reference']}")
    assert checkout.status_code == 200
    assert checkout.json()["merchant_name"] == "Merchant One"
    assert Decimal(checkout.json()["amount"]) == Decimal("0.05")
    assert checkout.json()["onchain_payment_id"] == payment["onchain_payment_id"]
    assert checkout.json()["onchain_reference_hash"] == payment["onchain_reference_hash"]
    assert checkout.json()["onchain_state"] == "NOT_CREATED"
    assert "merchant_id" not in checkout.json()

    listed = await client.get("/api/v1/payments")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    cancelled = await client.post(f"/api/v1/payments/{payment['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert (await client.get(f"/api/v1/payments/checkout/{payment['reference']}")).json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_chain_transaction_submission_is_persisted_and_idempotent(client):
    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("chain-merchant@example.com", "Chain Merchant"),
    )
    created = await client.post("/api/v1/payments", json=payment_payload())
    payment_id = created.json()["id"]
    transaction_hash = "0x" + "a" * 64
    body = {"operation": "CREATE_PAYMENT", "transaction_hash": transaction_hash}

    submitted = await client.post(f"/api/v1/payments/{payment_id}/chain-transactions", json=body)
    assert submitted.status_code == 202
    transaction = submitted.json()
    assert transaction["payment_request_id"] == payment_id
    assert transaction["chain_id"] == 11155111
    assert transaction["status"] == "PENDING"
    assert transaction["transaction_hash"] == transaction_hash

    duplicate = await client.post(f"/api/v1/payments/{payment_id}/chain-transactions", json=body)
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == transaction["id"]

    history = await client.get(f"/api/v1/payments/{payment_id}/chain-transactions")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [transaction["id"]]


@pytest.mark.asyncio
async def test_chain_receipt_refresh_persists_mined_state_and_escrow_events(client, monkeypatch):
    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("receipt-merchant@example.com", "Receipt Merchant"),
    )
    created = await client.post("/api/v1/payments", json=payment_payload())
    payment = created.json()
    transaction_hash = "0x" + "a" * 64
    transaction = await client.post(
        f"/api/v1/payments/{payment['id']}/chain-transactions",
        json={"operation": "CREATE_PAYMENT", "transaction_hash": transaction_hash},
    )
    escrow_address = "0x" + "c" * 40
    create_topic = "0x2432a880d5819fc8934f37ce832328c90be85389c2d59def524359aabcab950d"
    merchant_wallet_address = "0x" + "e" * 40
    create_block_hash = "0x" + "d" * 64
    customer_wallet_address = "0x" + "f" * 40
    deposit_hash = "0x" + "9" * 64
    deposit_topic = "0xf5430bdd23e03f0d1e5c026bd89c405381947b03d2a8471f2a7cc7b3fcb9fd57"
    deposit_block_hash = "0x" + "8" * 64
    create_receipt = {
        "transactionHash": transaction_hash,
        "status": "0x1",
        "blockNumber": "0x5",
        "blockHash": create_block_hash,
        "logs": [
            {
                "address": escrow_address,
                "topics": [
                    create_topic,
                    payment["onchain_payment_id"],
                    payment["onchain_reference_hash"],
                    "0x" + "0" * 24 + merchant_wallet_address[2:],
                ],
                "data": "0x1234",
                "logIndex": "0x0",
            }
        ],
    }
    deposit_receipt = {
        "transactionHash": deposit_hash,
        "status": "0x1",
        "blockNumber": "0x7",
        "blockHash": deposit_block_hash,
        "logs": [
            {
                "address": escrow_address,
                "topics": [
                    deposit_topic,
                    payment["onchain_payment_id"],
                    "0x" + "0" * 24 + customer_wallet_address[2:],
                ],
                "data": "0x",
                "logIndex": "0x0",
            }
        ],
    }
    deposit_transaction = {
        "to": escrow_address,
        "from": customer_wallet_address,
        "input": "0x42ef5fbb" + payment["onchain_payment_id"][2:],
        "value": hex(int(Decimal(payment["amount"]) * Decimal("1e18"))),
    }

    async def fake_chain_id():
        return 11155111

    async def fake_rpc_call(method, params=None):
        if method == "eth_getTransactionReceipt":
            return deposit_receipt if params and params[0] == deposit_hash else create_receipt
        if method == "eth_getTransactionByHash":
            return deposit_transaction
        if method == "eth_blockNumber":
            return "0x8"
        raise AssertionError(f"Unexpected JSON-RPC method: {method}")

    monkeypatch.setattr(payments_api, "get_rpc_chain_id", fake_chain_id)
    monkeypatch.setattr(payments_api, "rpc_call", fake_rpc_call)
    monkeypatch.setattr(
        payments_api,
        "get_settings",
        lambda: SimpleNamespace(
            escrow_contract_address=escrow_address,
            evm_chain_id=11155111,
            checkout_enabled=True,
            authorizer_private_key="configured",
        ),
    )

    refreshed = await client.post(
        f"/api/v1/payments/{payment['id']}/chain-transactions/{transaction.json()['id']}/refresh"
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "MINED"
    assert refreshed.json()["block_number"] == 5
    assert refreshed.json()["confirmations"] == 4
    payment_state = await client.get(f"/api/v1/payments/{payment['id']}")
    assert payment_state.json()["status"] == "AWAITING_PAYMENT"
    assert payment_state.json()["onchain_state"] == "CREATED"
    assert payment_state.json()["merchant_wallet_address"] == merchant_wallet_address

    events = await client.get(f"/api/v1/payments/{payment['id']}/chain-events")
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["event_name"] == create_topic
    assert events.json()[0]["event_data"]["data"] == "0x1234"

    deposited = await client.post(
        f"/api/v1/payments/checkout/{payment['reference']}/deposit",
        json={"operation": "DEPOSIT", "transaction_hash": deposit_hash},
    )
    assert deposited.status_code == 201
    assert deposited.json()["status"] == "MINED"
    updated = await client.get(f"/api/v1/payments/{payment['id']}")
    assert updated.json()["onchain_state"] == "DEPOSITED"
    assert updated.json()["status"] == "RISK_ASSESSMENT"
    assert updated.json()["customer_wallet_address"] == customer_wallet_address


@pytest.mark.asyncio
async def test_payment_chain_and_amount_are_validated(client):
    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("merchant@example.com", "Merchant One"),
    )
    unsupported_chain = await client.post("/api/v1/payments", json=payment_payload(chain_id=1))
    assert unsupported_chain.status_code == 422

    invalid_amount = await client.post("/api/v1/payments", json=payment_payload(amount="0"))
    assert invalid_amount.status_code == 422


@pytest.mark.asyncio
async def test_merchants_cannot_access_each_others_payment_requests(client):
    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("first@example.com", "First Merchant"),
    )
    first_payment = await client.post("/api/v1/payments", json=payment_payload())
    payment = first_payment.json()
    await client.post("/api/v1/auth/logout")

    await client.post(
        "/api/v1/auth/register",
        json=registration_payload("second@example.com", "Second Merchant"),
    )
    private_detail = await client.get(f"/api/v1/payments/{payment['id']}")
    assert private_detail.status_code == 404
    private_cancel = await client.post(f"/api/v1/payments/{payment['id']}/cancel")
    assert private_cancel.status_code == 404
    public_checkout = await client.get(f"/api/v1/payments/checkout/{payment['reference']}")
    assert public_checkout.status_code == 200


@pytest.mark.asyncio
async def test_checkout_config_disables_undeployed_escrow(client, monkeypatch):
    escrow_address = "0x" + "c" * 40
    monkeypatch.setattr(
        chain_api,
        "get_settings",
        lambda: SimpleNamespace(evm_chain_id=31337, escrow_contract_address=escrow_address, checkout_enabled=False, authorizer_private_key=""),
    )

    async def fake_chain_id():
        return 31337

    async def fake_rpc_call(method, params=None):
        assert method == "eth_getCode"
        assert params == [escrow_address, "latest"]
        return "0x"

    monkeypatch.setattr(chain_api, "get_rpc_chain_id", fake_chain_id)
    monkeypatch.setattr(chain_api, "rpc_call", fake_rpc_call)

    response = await client.get("/api/v1/chain/checkout-config")

    assert response.status_code == 200
    assert response.json() == {
        "chain_id": 31337,
        "escrow_address": None,
        "escrow_deployed": False,
        "checkout_enabled": False,
    }


@pytest.mark.asyncio
async def test_checkout_config_enables_only_deployed_escrow(client, monkeypatch):
    escrow_address = "0x" + "c" * 40
    monkeypatch.setattr(
        chain_api,
        "get_settings",
        lambda: SimpleNamespace(evm_chain_id=31337, escrow_contract_address=escrow_address, checkout_enabled=True, authorizer_private_key="configured"),
    )

    async def fake_chain_id():
        return 31337

    async def fake_rpc_call(method, params=None):
        assert method == "eth_getCode"
        return "0x60006000"

    monkeypatch.setattr(chain_api, "get_rpc_chain_id", fake_chain_id)
    monkeypatch.setattr(chain_api, "rpc_call", fake_rpc_call)

    response = await client.get("/api/v1/chain/checkout-config")

    assert response.status_code == 200
    assert response.json() == {
        "chain_id": 31337,
        "escrow_address": escrow_address,
        "escrow_deployed": True,
        "checkout_enabled": True,
    }