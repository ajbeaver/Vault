from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from vault.config import DependencyError, ValidationError


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


def _require_web3():
    try:
        from web3 import HTTPProvider, Web3
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise DependencyError(
            "Missing dependency: web3 is required. Run `pip install -e .`."
        ) from exc
    return HTTPProvider, Web3


class EVMClient:
    def __init__(self, network: dict[str, Any]) -> None:
        self.network = network
        http_provider, web3_cls = _require_web3()
        self.w3 = web3_cls(http_provider(network["rpc_url"]))
        if not self.w3.is_connected():
            raise ValidationError(f"Could not connect to RPC at {redact_rpc_url(network['rpc_url'])}.")

    def doctor(self) -> dict[str, Any]:
        remote_chain_id = int(self.w3.eth.chain_id)
        latest_block = int(self.w3.eth.block_number)
        matches_expected = remote_chain_id == int(self.network["chain_id"])
        if not matches_expected:
            raise ValidationError(
                f"RPC chain ID mismatch: expected {self.network['chain_id']}, got {remote_chain_id}."
            )
        return {
            "summary": f"RPC check passed for {self.network['name']}",
            "network": self.network["name"],
            "provider": self.network.get("provider", "custom"),
            "chain_id": self.network["chain_id"],
            "rpc_chain_id": remote_chain_id,
            "latest_block": latest_block,
            "rpc_url": redact_rpc_url(self.network["rpc_url"]),
        }

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        return {
            "transaction_hash": prefixed_hex(receipt["transactionHash"]),
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "block_number": int(receipt["blockNumber"]),
            "block_hash": prefixed_hex(receipt["blockHash"]),
            "status": int(receipt["status"]),
            "gas_used": int(receipt["gasUsed"]),
            "effective_gas_price": str(int(receipt.get("effectiveGasPrice", 0))),
        }

    def get_native_balance(self, address: str) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(address)
        wei_balance = self.w3.eth.get_balance(checksum)
        return {
            "summary": f"Native balance for {checksum} on {self.network['name']}",
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "address": checksum,
            "asset_type": "native",
            "symbol": self.network["symbol"],
            "balance_wei": str(wei_balance),
            "balance": format_units(wei_balance, 18),
        }

    def get_token_balance(self, address: str, token_address: str) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(address)
        token = self._token_contract(token_address)
        decimals = int(token.functions.decimals().call())
        symbol = token.functions.symbol().call()
        raw_balance = int(token.functions.balanceOf(checksum).call())
        return {
            "summary": f"Token balance for {checksum} on {self.network['name']}",
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "address": checksum,
            "asset_type": "erc20",
            "token_address": token.address,
            "symbol": symbol,
            "decimals": decimals,
            "balance_raw": str(raw_balance),
            "balance": format_units(raw_balance, decimals),
        }

    def prepare_native_transfer(
        self,
        from_address: str,
        to_address: str,
        amount: str,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        sender = self.w3.to_checksum_address(from_address)
        recipient = self.w3.to_checksum_address(to_address)
        value = parse_units(amount, 18)
        tx: dict[str, Any] = {
            "chainId": self.network["chain_id"],
            "from": sender,
            "to": recipient,
            "value": value,
            "nonce": self._resolve_nonce(sender, nonce),
        }
        fees = self._resolve_fee_fields(gas_price_gwei, max_fee_per_gas_gwei, max_priority_fee_per_gas_gwei)
        tx.update(fees)
        tx["gas"] = gas_limit or self.w3.eth.estimate_gas(tx)
        max_fee_cost = estimate_max_fee_cost(tx)
        return {
            "summary": f"Prepared native transfer on {self.network['name']}",
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "asset_type": "native",
            "symbol": self.network["symbol"],
            "from_address": sender,
            "to_address": recipient,
            "amount": amount,
            "amount_wei": str(value),
            "nonce": tx["nonce"],
            "gas_limit": tx["gas"],
            "fee_model": fee_model(tx),
            "max_fee_cost_wei": str(max_fee_cost),
            "estimated_total_cost_wei": str(value + max_fee_cost),
            "tx": tx,
        }

    def send_native(
        self,
        from_address: str,
        private_key_hex: str,
        to_address: str,
        amount: str,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        prepared = self.prepare_native_transfer(
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        prepared["transaction_hash"] = self._sign_and_send(prepared["tx"], private_key_hex)
        prepared["summary"] = f"Submitted native transfer on {self.network['name']}"
        prepared.pop("tx", None)
        return prepared

    def prepare_token_transfer(
        self,
        from_address: str,
        token_address: str,
        to_address: str,
        amount: str,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        sender = self.w3.to_checksum_address(from_address)
        recipient = self.w3.to_checksum_address(to_address)
        token = self._token_contract(token_address)
        decimals = int(token.functions.decimals().call())
        symbol = token.functions.symbol().call()
        value = parse_units(amount, decimals)
        tx = token.functions.transfer(recipient, value).build_transaction(
            {
                "chainId": self.network["chain_id"],
                "from": sender,
                "nonce": self._resolve_nonce(sender, nonce),
            }
        )
        fees = self._resolve_fee_fields(gas_price_gwei, max_fee_per_gas_gwei, max_priority_fee_per_gas_gwei)
        tx.update(fees)
        tx["gas"] = gas_limit or self.w3.eth.estimate_gas(tx)
        max_fee_cost = estimate_max_fee_cost(tx)
        return {
            "summary": f"Prepared ERC-20 transfer on {self.network['name']}",
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "asset_type": "erc20",
            "symbol": symbol,
            "token_address": token.address,
            "from_address": sender,
            "to_address": recipient,
            "amount": amount,
            "amount_raw": str(value),
            "decimals": decimals,
            "nonce": tx["nonce"],
            "gas_limit": tx["gas"],
            "fee_model": fee_model(tx),
            "max_fee_cost_wei": str(max_fee_cost),
            "estimated_total_cost_wei": str(max_fee_cost),
            "tx": tx,
        }

    def send_token(
        self,
        from_address: str,
        private_key_hex: str,
        token_address: str,
        to_address: str,
        amount: str,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        prepared = self.prepare_token_transfer(
            from_address=from_address,
            token_address=token_address,
            to_address=to_address,
            amount=amount,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        prepared["transaction_hash"] = self._sign_and_send(prepared["tx"], private_key_hex)
        prepared["summary"] = f"Submitted ERC-20 transfer on {self.network['name']}"
        prepared.pop("tx", None)
        return prepared

    def send_prepared(self, prepared: dict[str, Any], private_key_hex: str) -> dict[str, Any]:
        tx = prepared.get("tx")
        if not isinstance(tx, dict):
            raise ValidationError("Prepared transaction is missing signing payload.")
        payload = dict(prepared)
        payload["transaction_hash"] = self._sign_and_send(tx, private_key_hex)
        if payload["asset_type"] == "erc20":
            payload["summary"] = f"Submitted ERC-20 transfer on {self.network['name']}"
        else:
            payload["summary"] = f"Submitted native transfer on {self.network['name']}"
        payload.pop("tx", None)
        return payload

    def simulate_transaction(self, tx: dict[str, Any]) -> dict[str, Any]:
        try:
            self.w3.eth.call(tx)
            gas_estimate = self.w3.eth.estimate_gas(tx)
            return {
                "status": "success",
                "gas_estimate": int(gas_estimate),
                "revert_reason": None,
            }
        except Exception as exc:  # pragma: no cover - provider-specific error formatting
            return {
                "status": "reverted",
                "gas_estimate": None,
                "revert_reason": str(exc),
            }

    def _resolve_nonce(self, sender: str, nonce: int | None) -> int:
        return nonce if nonce is not None else self.w3.eth.get_transaction_count(sender)

    def _resolve_fee_fields(
        self,
        gas_price_gwei: str | None,
        max_fee_per_gas_gwei: str | None,
        max_priority_fee_per_gas_gwei: str | None,
    ) -> dict[str, int]:
        if gas_price_gwei and (max_fee_per_gas_gwei or max_priority_fee_per_gas_gwei):
            raise ValidationError("Use either legacy gas price or EIP-1559 fee fields, not both.")
        if gas_price_gwei:
            return {"gasPrice": self.w3.to_wei(Decimal(gas_price_gwei), "gwei")}
        if max_fee_per_gas_gwei or max_priority_fee_per_gas_gwei:
            priority = self.w3.to_wei(Decimal(max_priority_fee_per_gas_gwei or "2"), "gwei")
            maximum = self.w3.to_wei(Decimal(max_fee_per_gas_gwei or "0"), "gwei")
            if maximum <= 0:
                latest_block = self.w3.eth.get_block("latest")
                base_fee = int(latest_block.get("baseFeePerGas", 0))
                maximum = (base_fee * 2) + priority
            return {
                "maxFeePerGas": maximum,
                "maxPriorityFeePerGas": priority,
            }

        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas")
        if base_fee is None:
            return {"gasPrice": int(self.w3.eth.gas_price)}
        try:
            priority = int(self.w3.eth.max_priority_fee)
        except Exception:  # pragma: no cover - provider-specific
            priority = self.w3.to_wei(2, "gwei")
        return {
            "maxFeePerGas": int(base_fee) * 2 + priority,
            "maxPriorityFeePerGas": priority,
        }

    def _token_contract(self, token_address: str):
        checksum = self.w3.to_checksum_address(token_address)
        return self.w3.eth.contract(address=checksum, abi=ERC20_ABI)

    def _sign_and_send(self, tx: dict[str, Any], private_key_hex: str) -> str:
        signed = self.w3.eth.account.sign_transaction(tx, bytes.fromhex(private_key_hex))
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        value = tx_hash.hex()
        return value if value.startswith("0x") else f"0x{value}"


def parse_units(value: str, decimals: int) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"Invalid decimal amount: {value}") from exc
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero.")
    scale = Decimal(10) ** decimals
    raw = amount * scale
    if raw != raw.to_integral_value():
        raise ValidationError(f"Amount exceeds supported precision for {decimals} decimals.")
    return int(raw)


def format_units(value: int, decimals: int) -> str:
    amount = Decimal(value) / (Decimal(10) ** decimals)
    return format(amount.normalize(), "f")


def fee_model(tx: dict[str, Any]) -> str:
    return "eip1559" if "maxFeePerGas" in tx else "legacy"


def estimate_max_fee_cost(tx: dict[str, Any]) -> int:
    gas_limit = int(tx["gas"])
    if "maxFeePerGas" in tx:
        return gas_limit * int(tx["maxFeePerGas"])
    return gas_limit * int(tx["gasPrice"])


def prefixed_hex(value: Any) -> str:
    if hasattr(value, "hex"):
        raw = value.hex()
    else:
        raw = str(value)
    return raw if raw.startswith("0x") else f"0x{raw}"


def redact_rpc_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.path:
        return url
    parts = parsed.path.rstrip("/").split("/")
    if parts and len(parts[-1]) >= 8:
        parts[-1] = "***"
        return urlunsplit((parsed.scheme, parsed.netloc, "/".join(parts), parsed.query, parsed.fragment))
    return url
