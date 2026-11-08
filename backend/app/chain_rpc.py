import itertools

import httpx

from app.config import get_settings

_request_ids = itertools.count(1)


class ChainRPCError(Exception):
    pass


async def rpc_call(method: str, params: list[object] | None = None) -> object:
    rpc_url = get_settings().evm_rpc_url
    if not rpc_url:
        raise ChainRPCError("EVM_RPC_URL is not configured")

    request_id = next(_request_ids)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                rpc_url,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or []},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ChainRPCError("The configured EVM RPC endpoint is unavailable") from error

    if not isinstance(payload, dict) or payload.get("id") != request_id:
        raise ChainRPCError("The configured EVM RPC endpoint returned an invalid response")
    if payload.get("error") is not None:
        raise ChainRPCError("The configured EVM RPC endpoint rejected the request")
    return payload.get("result")


async def get_rpc_chain_id() -> int:
    result = await rpc_call("eth_chainId")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ChainRPCError("The configured EVM RPC endpoint returned an invalid chain ID")
    try:
        return int(result, 16)
    except ValueError as error:
        raise ChainRPCError("The configured EVM RPC endpoint returned an invalid chain ID") from error
