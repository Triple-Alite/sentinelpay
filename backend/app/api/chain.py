from fastapi import APIRouter, HTTPException, status

from app.chain_rpc import ChainRPCError, get_rpc_chain_id, rpc_call
from app.config import get_settings

router = APIRouter(prefix="/api/v1/chain", tags=["chain"])


@router.get("/health")
async def chain_health() -> dict[str, int | bool | str]:
    settings = get_settings()
    try:
        connected_chain_id = await get_rpc_chain_id()
    except ChainRPCError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    if connected_chain_id != settings.evm_chain_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Connected chain {connected_chain_id} does not match configured chain {settings.evm_chain_id}",
        )

    return {
        "status": "connected",
        "chain_id": connected_chain_id,
        "escrow_configured": bool(settings.escrow_contract_address),
    }


@router.get("/checkout-config")
async def checkout_config() -> dict[str, int | bool | str | None]:
    settings = get_settings()
    try:
        connected_chain_id = await get_rpc_chain_id()
    except ChainRPCError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    address = settings.escrow_contract_address.strip()
    deployed = False
    if connected_chain_id == settings.evm_chain_id and address:
        try:
            code = await rpc_call("eth_getCode", [address, "latest"])
        except ChainRPCError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        deployed = isinstance(code, str) and code.startswith("0x") and len(code) > 2

    return {
        "chain_id": connected_chain_id,
        "escrow_address": address if deployed else None,
        "escrow_deployed": deployed,
        "checkout_enabled": (
            settings.checkout_enabled
            and connected_chain_id == settings.evm_chain_id
            and deployed
            and bool(settings.authorizer_private_key)
        ),
    }
