from datetime import UTC, datetime, timedelta
from decimal import Decimal
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chain_rpc import ChainRPCError, get_rpc_chain_id, rpc_call
from app.chain_worker import EscrowChainWorker
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Merchant, PaymentChainTransaction, PaymentRequest, User
from app.models import PaymentChainEvent
from app.schemas import (
    ChainTransactionRequest,
    ChainTransactionResponse,
    ChainEventResponse,
    CheckoutResponse,
    PaymentCreateRequest,
    PaymentResponse,
)
from app.security import is_expired

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


async def require_merchant(db: AsyncSession, user_id: uuid.UUID) -> Merchant:
    merchant = await db.scalar(select(Merchant).where(Merchant.user_id == user_id))
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant account required")
    if merchant.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant account is not active")
    return merchant


def payment_response(payment: PaymentRequest) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        reference=payment.reference,
        description=payment.description,
        amount=payment.amount,
        currency=payment.currency,
        token_address=payment.token_address,
        chain_id=payment.chain_id,
        onchain_payment_id=payment.onchain_payment_id,
        onchain_reference_hash=payment.onchain_reference_hash,
        merchant_wallet_address=payment.merchant_wallet_address,
        customer_wallet_address=payment.customer_wallet_address,
        onchain_state=payment.onchain_state,
        status=payment.status,
        expires_at=payment.expires_at,
        created_at=payment.created_at,
        checkout_url=f"/checkout/{payment.reference}",
    )


async def expire_if_needed(db: AsyncSession, payment: PaymentRequest) -> None:
    if payment.status in {"CREATED", "AWAITING_PAYMENT"} and is_expired(payment.expires_at):
        payment.status = "EXPIRED"
        payment.updated_at = datetime.now(UTC)
        await db.commit()


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    body: PaymentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    settings = get_settings()
    if body.chain_id != settings.evm_chain_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported chain. This environment is configured for chain {settings.evm_chain_id}.",
        )
    merchant = await require_merchant(db, user.id)
    now = datetime.now(UTC)
    payment = PaymentRequest(
        merchant_id=merchant.id,
        reference=secrets.token_urlsafe(24),
        description=body.description.strip(),
        amount=body.amount,
        currency=body.currency,
        token_address=None,
        chain_id=body.chain_id,
        onchain_payment_id=f"0x{secrets.token_hex(32)}",
        onchain_reference_hash=f"0x{secrets.token_hex(32)}",
        onchain_state="NOT_CREATED",
        status="CREATED",
        expires_at=now + timedelta(minutes=body.expires_in_minutes),
        success_url=str(body.success_url) if body.success_url else None,
        cancel_url=str(body.cancel_url) if body.cancel_url else None,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment_response(payment)


@router.get("", response_model=list[PaymentResponse])
async def list_payments(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentResponse]:
    merchant = await require_merchant(db, user.id)
    payments = await db.scalars(
        select(PaymentRequest)
        .where(PaymentRequest.merchant_id == merchant.id)
        .order_by(desc(PaymentRequest.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = list(payments)
    for payment in result:
        await expire_if_needed(db, payment)
    return [payment_response(payment) for payment in result]


@router.get("/checkout/{reference}", response_model=CheckoutResponse)
async def read_checkout(reference: str, db: AsyncSession = Depends(get_db)) -> CheckoutResponse:
    payment = await db.scalar(
        select(PaymentRequest)
        .where(PaymentRequest.reference == reference)
        .options(selectinload(PaymentRequest.merchant))
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    await expire_if_needed(db, payment)
    return CheckoutResponse(
        reference=payment.reference,
        merchant_name=payment.merchant.business_name,
        description=payment.description,
        amount=payment.amount,
        currency=payment.currency,
        chain_id=payment.chain_id,
        onchain_payment_id=payment.onchain_payment_id,
        onchain_reference_hash=payment.onchain_reference_hash,
        merchant_wallet_address=payment.merchant_wallet_address,
        customer_wallet_address=payment.customer_wallet_address,
        onchain_state=payment.onchain_state,
        status=payment.status,
        expires_at=payment.expires_at,
    )


@router.post(
    "/checkout/{reference}/deposit",
    response_model=ChainTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_checkout_deposit(
    reference: str,
    body: ChainTransactionRequest,
    db: AsyncSession = Depends(get_db),
) -> ChainTransactionResponse:
    if body.operation != "DEPOSIT":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only deposits can be recorded from checkout")
    payment = await db.scalar(select(PaymentRequest).where(PaymentRequest.reference == reference))
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    if payment.status != "AWAITING_PAYMENT" or payment.onchain_state != "CREATED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment is not ready for a customer deposit")

    settings = get_settings()
    if (
        not settings.checkout_enabled
        or not settings.authorizer_private_key
        or payment.chain_id != settings.evm_chain_id
        or not settings.escrow_contract_address
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Escrow is not configured for this payment network")

    try:
        connected_chain_id = await get_rpc_chain_id()
        transaction_value = await rpc_call("eth_getTransactionByHash", [body.transaction_hash.lower()])
        receipt = await rpc_call("eth_getTransactionReceipt", [body.transaction_hash.lower()])
        latest_block_value = await rpc_call("eth_blockNumber")
    except ChainRPCError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    if connected_chain_id != payment.chain_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RPC chain does not match the payment network")
    if not isinstance(transaction_value, dict) or not isinstance(receipt, dict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deposit transaction is not confirmed yet")
    if receipt.get("status") != "0x1":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Deposit transaction reverted")

    expected_calldata = "0x42ef5fbb" + str(payment.onchain_payment_id or "")[2:]
    expected_escrow = settings.escrow_contract_address.lower()
    if (
        str(transaction_value.get("to", "")).lower() != expected_escrow
        or str(transaction_value.get("input", "")).lower() != expected_calldata.lower()
        or int(str(transaction_value.get("value", "0x0")), 16) != int(payment.amount * Decimal("1e18"))
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transaction does not match this escrow deposit")

    receipt_hash = receipt.get("transactionHash")
    block_number_value = receipt.get("blockNumber")
    block_hash = receipt.get("blockHash")
    if not isinstance(receipt_hash, str) or receipt_hash.lower() != body.transaction_hash.lower():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RPC returned an invalid transaction receipt")
    if not isinstance(block_number_value, str) or not isinstance(block_hash, str) or not isinstance(latest_block_value, str):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RPC returned an incomplete deposit receipt")

    deposit_topic = "0xf5430bdd23e03f0d1e5c026bd89c405381947b03d2a8471f2a7cc7b3fcb9fd57"
    customer_address = None
    matching_log = None
    for log in receipt.get("logs", []):
        topics = log.get("topics") if isinstance(log, dict) else None
        if (
            not isinstance(topics, list)
            or len(topics) < 3
            or not isinstance(topics[0], str)
            or not isinstance(topics[1], str)
            or not isinstance(topics[2], str)
            or str(log.get("address", "")).lower() != expected_escrow
            or topics[0].lower() != deposit_topic
            or topics[1].lower() != str(payment.onchain_payment_id or "").lower()
            or len(topics[2]) != 66
        ):
            continue
        customer_address = "0x" + topics[2][-40:]
        matching_log = log
        break
    if customer_address is None or matching_log is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expected escrow deposit event was not found")
    if str(transaction_value.get("from", "")).lower() != customer_address.lower():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Deposit sender does not match the escrow event")

    existing = await db.scalar(
        select(PaymentChainTransaction).where(
            PaymentChainTransaction.chain_id == payment.chain_id,
            PaymentChainTransaction.transaction_hash == body.transaction_hash.lower(),
        )
    )
    if existing is not None:
        if existing.payment_request_id != payment.id or existing.operation != "DEPOSIT":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction is already linked to another payment")
        return ChainTransactionResponse.model_validate(existing)

    block_number = int(block_number_value, 16)
    latest_block = int(latest_block_value, 16)
    log_index_value = matching_log.get("logIndex")
    if not isinstance(log_index_value, str):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RPC returned a deposit event without a log index")
    transaction = PaymentChainTransaction(
        payment_request_id=payment.id,
        chain_id=payment.chain_id,
        operation="DEPOSIT",
        transaction_hash=body.transaction_hash.lower(),
        status="MINED",
        block_number=block_number,
        block_hash=block_hash.lower(),
        confirmations=max(0, latest_block - block_number + 1),
        confirmed_at=datetime.now(UTC),
    )
    db.add(transaction)
    db.add(
        PaymentChainEvent(
            payment_request_id=payment.id,
            chain_id=payment.chain_id,
            transaction_hash=body.transaction_hash.lower(),
            log_index=int(log_index_value, 16),
            block_number=block_number,
            block_hash=block_hash.lower(),
            event_name=deposit_topic,
            event_data={"address": expected_escrow, "topics": matching_log["topics"], "data": matching_log.get("data", "0x")},
            processed_at=datetime.now(UTC),
        )
    )
    payment.customer_wallet_address = customer_address.lower()
    payment.onchain_state = "DEPOSITED"
    payment.status = "RISK_ASSESSMENT"
    await db.commit()
    await db.refresh(transaction)
    return ChainTransactionResponse.model_validate(transaction)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def read_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    await expire_if_needed(db, payment)
    return payment_response(payment)


@router.post("/{payment_id}/release-authorization")
async def create_release_authorization(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    if payment.status != "APPROVED" or payment.onchain_state != "APPROVED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an approved escrow can be released")
    if not payment.merchant_wallet_address or not payment.customer_wallet_address:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Escrow participant wallets are not confirmed")

    settings = get_settings()
    if not settings.escrow_contract_address or payment.chain_id != settings.evm_chain_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Escrow is not configured for this payment network")
    try:
        connected_chain_id = await get_rpc_chain_id()
    except ChainRPCError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    if connected_chain_id != payment.chain_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RPC chain does not match the payment network")

    authorization = EscrowChainWorker().build_release_authorization(
        payment_id=str(payment.onchain_payment_id),
        reference_hash=str(payment.onchain_reference_hash),
        merchant=payment.merchant_wallet_address,
        customer=payment.customer_wallet_address,
        token_address=payment.token_address or "0x0000000000000000000000000000000000000000",
        amount=payment.amount,
        decision="ALLOW",
        expires_at=int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
        chain_id=payment.chain_id,
        contract_address=settings.escrow_contract_address,
        nonce=secrets.randbits(256),
    )
    authorization["nonce"] = str(authorization["nonce"])
    authorization["message"]["nonce"] = str(authorization["message"]["nonce"])
    return authorization


@router.post("/{payment_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    await expire_if_needed(db, payment)
    if payment.status not in {"CREATED", "AWAITING_PAYMENT"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment request can no longer be cancelled")
    payment.status = "CANCELLED"
    payment.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(payment)
    return payment_response(payment)


@router.post(
    "/{payment_id}/chain-transactions",
    response_model=ChainTransactionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_chain_transaction(
    payment_id: uuid.UUID,
    body: ChainTransactionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChainTransactionResponse:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    if payment.onchain_payment_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment has no on-chain identifier")

    existing = await db.scalar(
        select(PaymentChainTransaction).where(
            PaymentChainTransaction.chain_id == payment.chain_id,
            PaymentChainTransaction.transaction_hash == body.transaction_hash.lower(),
        )
    )
    if existing is not None:
        if existing.payment_request_id != payment.id or existing.operation != body.operation:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction is already linked to another operation")
        return ChainTransactionResponse.model_validate(existing)

    transaction = PaymentChainTransaction(
        payment_request_id=payment.id,
        chain_id=payment.chain_id,
        operation=body.operation,
        transaction_hash=body.transaction_hash.lower(),
        status="PENDING",
    )
    db.add(transaction)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction is already recorded") from None
    await db.refresh(transaction)
    return ChainTransactionResponse.model_validate(transaction)


@router.get("/{payment_id}/chain-transactions", response_model=list[ChainTransactionResponse])
async def list_chain_transactions(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChainTransactionResponse]:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest.id).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")

    transactions = await db.scalars(
        select(PaymentChainTransaction)
        .where(PaymentChainTransaction.payment_request_id == payment_id)
        .order_by(PaymentChainTransaction.submitted_at)
    )
    return [ChainTransactionResponse.model_validate(transaction) for transaction in transactions]

@router.post(
    "/{payment_id}/chain-transactions/{transaction_id}/refresh",
    response_model=ChainTransactionResponse,
)
async def refresh_chain_transaction(
    payment_id: uuid.UUID,
    transaction_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChainTransactionResponse:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")
    transaction = await db.scalar(
        select(PaymentChainTransaction).where(
            PaymentChainTransaction.id == transaction_id,
            PaymentChainTransaction.payment_request_id == payment.id,
        )
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chain transaction not found")

    settings = get_settings()
    try:
        connected_chain_id = await get_rpc_chain_id()
        if connected_chain_id != payment.chain_id:
            raise ChainRPCError(
                f"Connected chain {connected_chain_id} does not match payment chain {payment.chain_id}"
            )
        receipt = await rpc_call("eth_getTransactionReceipt", [transaction.transaction_hash])
        if receipt is None:
            if transaction.status != "PENDING":
                await db.execute(
                    delete(PaymentChainEvent)
                    .where(
                        PaymentChainEvent.chain_id == transaction.chain_id,
                        PaymentChainEvent.transaction_hash == transaction.transaction_hash,
                    )
                )
                transaction.status = "PENDING"
                transaction.block_number = None
                transaction.block_hash = None
                transaction.confirmations = 0
                transaction.confirmed_at = None
                await db.commit()
            return ChainTransactionResponse.model_validate(transaction)
        receipt_hash = receipt.get("transactionHash") if isinstance(receipt, dict) else None
        if not isinstance(receipt_hash, str) or receipt_hash.lower() != transaction.transaction_hash:
            raise ChainRPCError("The configured EVM RPC endpoint returned an invalid transaction receipt")
        receipt_status = receipt.get("status")
        if receipt_status not in {"0x0", "0x1"}:
            raise ChainRPCError("The configured EVM RPC endpoint returned an invalid receipt status")

        block_number_value = receipt.get("blockNumber")
        block_hash = receipt.get("blockHash")
        if not isinstance(block_number_value, str) or not isinstance(block_hash, str):
            raise ChainRPCError("The configured EVM RPC endpoint returned an incomplete transaction receipt")
        block_number = int(block_number_value, 16)
        latest_block_value = await rpc_call("eth_blockNumber")
        if not isinstance(latest_block_value, str):
            raise ChainRPCError("The configured EVM RPC endpoint returned an invalid block number")
        latest_block = int(latest_block_value, 16)
    except (ChainRPCError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    reorged = transaction.block_hash is not None and transaction.block_hash.lower() != block_hash.lower()
    if reorged or transaction.status in {"PENDING", "REORGED"}:
        await db.execute(
            delete(PaymentChainEvent).where(
                PaymentChainEvent.chain_id == transaction.chain_id,
                PaymentChainEvent.transaction_hash == transaction.transaction_hash,
            )
        )

    transaction.status = "MINED" if receipt_status == "0x1" else "FAILED"
    transaction.block_number = block_number
    transaction.block_hash = block_hash.lower()
    transaction.confirmations = max(0, latest_block - block_number + 1)
    transaction.failure_reason = None if receipt_status == "0x1" else "Transaction reverted on chain"
    transaction.confirmed_at = datetime.now(UTC)

    expected_event_topics = {
        "CREATE_PAYMENT": "0x2432a880d5819fc8934f37ce832328c90be85389c2d59def524359aabcab950d",
        "DEPOSIT": "0xf5430bdd23e03f0d1e5c026bd89c405381947b03d2a8471f2a7cc7b3fcb9fd57",
        "RELEASE": "0x1e170c3b430cc6fdcdaa453c42619ac587e13793aa81a489fab9ebd7019c2efb",
    }
    expected_event_topic = expected_event_topics.get(transaction.operation)
    matching_event_found = False
    expected_escrow = settings.escrow_contract_address.lower()
    logs = receipt.get("logs", [])
    if expected_escrow and isinstance(logs, list):
        for log in logs:
            if not isinstance(log, dict):
                continue
            topics = log.get("topics")
            log_address = log.get("address")
            log_index_value = log.get("logIndex")
            if (
                not isinstance(topics, list)
                or len(topics) < 2
                or not isinstance(topics[0], str)
                or not isinstance(topics[1], str)
                or not isinstance(log_address, str)
                or log_address.lower() != expected_escrow
                or topics[1].lower() != (payment.onchain_payment_id or "").lower()
                or not isinstance(log_index_value, str)
            ):
                continue
            if expected_event_topic and topics[0].lower() == expected_event_topic:
                indexed_address = (
                    topics[3] if transaction.operation == "CREATE_PAYMENT" and len(topics) > 3
                    else topics[2] if transaction.operation in {"DEPOSIT", "RELEASE"} and len(topics) > 2
                    else None
                )
                if (
                    isinstance(indexed_address, str)
                    and len(indexed_address) == 66
                    and all(character in "0123456789abcdefABCDEF" for character in indexed_address[2:])
                ):
                    matching_event_found = True
                    wallet_address = "0x" + indexed_address[-40:]
                    if transaction.operation == "CREATE_PAYMENT":
                        payment.merchant_wallet_address = wallet_address.lower()
                    elif transaction.operation == "DEPOSIT":
                        payment.customer_wallet_address = wallet_address.lower()
                    elif transaction.operation == "RELEASE":
                        if wallet_address.lower() != (payment.merchant_wallet_address or "").lower():
                            matching_event_found = False
                            continue

            try:
                log_index = int(log_index_value, 16)
            except ValueError:
                continue
            existing_event = await db.scalar(
                select(PaymentChainEvent).where(
                    PaymentChainEvent.chain_id == transaction.chain_id,
                    PaymentChainEvent.transaction_hash == transaction.transaction_hash,
                    PaymentChainEvent.log_index == log_index,
                )
            )
            if existing_event is None:
                db.add(
                    PaymentChainEvent(
                        payment_request_id=payment.id,
                        chain_id=transaction.chain_id,
                        transaction_hash=transaction.transaction_hash,
                        log_index=log_index,
                        block_number=block_number,
                        block_hash=block_hash.lower(),
                        event_name=topics[0].lower(),
                        event_data={"address": log_address.lower(), "topics": topics, "data": log.get("data", "0x")},
                        processed_at=datetime.now(UTC),
                    )
                )

    if transaction.status == "MINED" and expected_event_topic:
        if not matching_event_found:
            transaction.status = "FAILED"
            transaction.failure_reason = "Expected escrow event was not found in the transaction receipt"
        elif transaction.operation == "CREATE_PAYMENT":
            payment.onchain_state = "CREATED"
            if payment.status == "CREATED":
                payment.status = "AWAITING_PAYMENT"
        elif transaction.operation == "DEPOSIT":
            payment.onchain_state = "DEPOSITED"
            payment.status = "RISK_ASSESSMENT"
        elif transaction.operation == "RELEASE":
            payment.onchain_state = "RELEASED"
            payment.status = "COMPLETED"

    await db.commit()
    await db.refresh(transaction)
    return ChainTransactionResponse.model_validate(transaction)


@router.get("/{payment_id}/chain-events", response_model=list[ChainEventResponse])
async def list_chain_events(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChainEventResponse]:
    merchant = await require_merchant(db, user.id)
    payment = await db.scalar(
        select(PaymentRequest.id).where(
            PaymentRequest.id == payment_id,
            PaymentRequest.merchant_id == merchant.id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment request not found")

    events = await db.scalars(
        select(PaymentChainEvent)
        .where(PaymentChainEvent.payment_request_id == payment_id)
        .order_by(PaymentChainEvent.block_number, PaymentChainEvent.log_index)
    )
    return [ChainEventResponse.model_validate(event) for event in events]