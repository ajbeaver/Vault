from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from vault.config import DependencyError, ValidationError


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
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
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
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

ERC20_METADATA_BYTES32_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "bytes32"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "bytes32"}],
        "type": "function",
    },
]

ERC165_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "interfaceId", "type": "bytes4"}],
        "name": "supportsInterface",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    }
]

ERC721_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
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
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

ERC1155_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "interfaceId", "type": "bytes4"}],
        "name": "supportsInterface",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "id", "type": "uint256"}],
        "name": "uri",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]

ERC165_INTERFACE_ID = "0x01ffc9a7"
ERC165_INVALID_INTERFACE_ID = "0xffffffff"
ERC721_INTERFACE_ID = "0x80ac58cd"
ERC721_METADATA_INTERFACE_ID = "0x5b5e139f"
ERC1155_INTERFACE_ID = "0xd9b67a26"
ERC1155_METADATA_URI_INTERFACE_ID = "0x0e89341c"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
EIP1967_IMPLEMENTATION_SLOT = int("360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc", 16)
EIP1967_ADMIN_SLOT = int("b53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103", 16)
EIP1967_BEACON_SLOT = int("a3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50", 16)


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

    def get_transaction_receipt_or_none(self, tx_hash: str) -> dict[str, Any] | None:
        try:
            return self.get_transaction_receipt(tx_hash)
        except Exception:  # pragma: no cover - provider-specific missing-tx behavior
            return None

    def get_latest_block_number(self) -> int:
        return int(self.w3.eth.block_number)

    def get_transaction_count(self, address: str) -> int:
        checksum = self.w3.to_checksum_address(address)
        return int(self.w3.eth.get_transaction_count(checksum))

    def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, Any]]:
        checksum = self.w3.to_checksum_address(address)
        needle = checksum.lower()
        rows: list[dict[str, Any]] = []
        for block_number in range(start_block, end_block + 1):
            block = self.w3.eth.get_block(block_number, full_transactions=True)
            for tx in block["transactions"]:
                from_address = self.w3.to_checksum_address(tx["from"])
                to_value = tx.get("to")
                to_address = self.w3.to_checksum_address(to_value) if to_value else None
                if from_address.lower() != needle and (to_address or "").lower() != needle:
                    continue
                rows.append(
                    {
                        "transaction_hash": prefixed_hex(tx["hash"]),
                        "network": self.network["name"],
                        "chain_id": self.network["chain_id"],
                        "block_number": int(tx["blockNumber"]),
                        "from_address": from_address,
                        "to_address": to_address,
                        "value_wei": str(int(tx["value"])),
                        "nonce": int(tx["nonce"]),
                    }
                )
        return rows

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

    def get_contract_read(
        self,
        address: str,
        abi: list[dict[str, Any]],
        function_name: str,
        args: list[Any] | None = None,
    ) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(address)
        code_size = self.get_code_size(checksum)
        result_type_hint = self._result_type_hint(abi, function_name)
        try:
            contract = self._contract(checksum, abi)
            result = getattr(contract.functions, function_name)(*(args or [])).call()
            return {
                "address": checksum,
                "call_succeeded": True,
                "result": normalize_contract_value(result),
                "result_type_hint": result_type_hint,
                "code_present": code_size > 0,
                "code_size_bytes": code_size,
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - provider and ABI specific
            return {
                "address": checksum,
                "call_succeeded": False,
                "result": None,
                "result_type_hint": result_type_hint,
                "code_present": code_size > 0,
                "code_size_bytes": code_size,
                "error": str(exc),
            }

    def prepare_contract_write(
        self,
        from_address: str,
        contract_address: str,
        abi: list[dict[str, Any]],
        function_name: str,
        args: list[Any] | None = None,
        value: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        sender = self.w3.to_checksum_address(from_address)
        contract = self._contract(contract_address, abi)
        if not self.has_code(contract.address):
            raise ValidationError(f"No contract code found at {contract.address}.")
        native_value = parse_units_allow_zero(value or "0", 18)
        tx = getattr(contract.functions, function_name)(*(args or [])).build_transaction(
            {
                "chainId": self.network["chain_id"],
                "from": sender,
                "nonce": self._resolve_nonce(sender, nonce),
                "value": native_value,
            }
        )
        fees = self._resolve_fee_fields(gas_price_gwei, max_fee_per_gas_gwei, max_priority_fee_per_gas_gwei)
        tx.update(fees)
        tx["gas"] = gas_limit or self.w3.eth.estimate_gas(tx)
        max_fee_cost = estimate_max_fee_cost(tx)
        return {
            "summary": f"Prepared contract write on {self.network['name']}",
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "asset_type": "contract",
            "from_address": sender,
            "to_address": contract.address,
            "contract_function": function_name,
            "args": normalize_contract_value(args or []),
            "value": format_units(native_value, 18),
            "value_wei": str(native_value),
            "data": tx["data"],
            "nonce": tx["nonce"],
            "gas_limit": tx["gas"],
            "fee_model": fee_model(tx),
            "max_fee_cost_wei": str(max_fee_cost),
            "estimated_total_cost_wei": str(native_value + max_fee_cost),
            "tx": tx,
        }

    def get_token_allowance(self, token_address: str, owner: str, spender: str) -> dict[str, Any]:
        token = self._token_contract(token_address)
        owner_checksum = self.w3.to_checksum_address(owner)
        spender_checksum = self.w3.to_checksum_address(spender)
        raw_decimals = self.safe_contract_call(token.address, ERC20_ABI, "decimals")
        decimals = int(raw_decimals) if raw_decimals is not None else 18
        raw_symbol = self.safe_contract_call(token.address, ERC20_ABI, "symbol")
        symbol = str(raw_symbol) if raw_symbol is not None else None
        raw_allowance = int(token.functions.allowance(owner_checksum, spender_checksum).call())
        return {
            "token_address": token.address,
            "owner_address": owner_checksum,
            "spender_address": spender_checksum,
            "symbol": symbol,
            "decimals": decimals,
            "allowance_raw": str(raw_allowance),
            "allowance": format_units(raw_allowance, decimals),
        }

    def prepare_token_approve(
        self,
        from_address: str,
        token_address: str,
        spender_address: str,
        amount: str,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        token = self._token_contract(token_address)
        decimals = int(token.functions.decimals().call())
        symbol = token.functions.symbol().call()
        raw_amount = parse_units_allow_zero(amount, decimals)
        prepared = self.prepare_contract_write(
            from_address=from_address,
            contract_address=token.address,
            abi=ERC20_ABI,
            function_name="approve",
            args=[self.w3.to_checksum_address(spender_address), raw_amount],
            value="0",
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        prepared.update(
            {
                "summary": f"Prepared ERC-20 approval on {self.network['name']}",
                "asset_type": "erc20_approval",
                "token_address": token.address,
                "spender_address": self.w3.to_checksum_address(spender_address),
                "symbol": symbol,
                "decimals": decimals,
                "amount": amount,
                "amount_raw": str(raw_amount),
                "value": "0",
                "value_wei": "0",
            }
        )
        return prepared

    def get_bytecode(self, address: str) -> str:
        checksum = self.w3.to_checksum_address(address)
        return prefixed_hex(self.w3.eth.get_code(checksum))

    def get_code_size(self, address: str) -> int:
        return len(bytes.fromhex(self.get_bytecode(address)[2:]))

    def has_code(self, address: str) -> bool:
        return self.get_code_size(address) > 0

    def safe_contract_call(self, address: str, abi: list[dict[str, Any]], function_name: str, *args: Any) -> Any | None:
        try:
            contract = self.w3.eth.contract(address=self.w3.to_checksum_address(address), abi=abi)
            return getattr(contract.functions, function_name)(*args).call()
        except Exception:  # pragma: no cover - provider and ABI specific
            return None

    def supports_interface(self, address: str, interface_id: str) -> bool:
        if not self.has_code(address):
            return False
        erc165 = self.safe_contract_call(address, ERC165_ABI, "supportsInterface", ERC165_INTERFACE_ID)
        invalid = self.safe_contract_call(address, ERC165_ABI, "supportsInterface", ERC165_INVALID_INTERFACE_ID)
        if erc165 is not True or invalid is True:
            return False
        return self.safe_contract_call(address, ERC165_ABI, "supportsInterface", interface_id) is True

    def detect_contract_interfaces(self, address: str) -> list[str]:
        if not self.has_code(address):
            return []
        interfaces: list[str] = []
        if self.safe_contract_call(address, ERC165_ABI, "supportsInterface", ERC165_INTERFACE_ID) is True:
            interfaces.append("erc165")
        if self.supports_interface(address, ERC721_INTERFACE_ID):
            interfaces.append("erc721")
        if self.supports_interface(address, ERC721_METADATA_INTERFACE_ID):
            interfaces.append("erc721_metadata")
        if self.supports_interface(address, ERC1155_INTERFACE_ID):
            interfaces.append("erc1155")
        if self.supports_interface(address, ERC1155_METADATA_URI_INTERFACE_ID):
            interfaces.append("erc1155_metadata_uri")
        if self._detect_erc20(address):
            interfaces.append("erc20")
        return interfaces

    def read_proxy_hints(self, address: str) -> dict[str, Any]:
        implementation = self._read_storage_address(address, EIP1967_IMPLEMENTATION_SLOT)
        admin = self._read_storage_address(address, EIP1967_ADMIN_SLOT)
        beacon = self._read_storage_address(address, EIP1967_BEACON_SLOT)
        return {
            "implementation": implementation,
            "admin": admin,
            "beacon": beacon,
            "is_proxy": any((implementation, admin, beacon)),
        }

    def inspect_address(self, address: str) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(address)
        code_size = self.get_code_size(checksum)
        is_contract = code_size > 0
        payload: dict[str, Any] = {
            "address": checksum,
            "classification": "contract" if is_contract else "eoa",
            "nonce": self.get_transaction_count(checksum),
            "code_present": is_contract,
            "code_size_bytes": code_size,
            "detected_interfaces": self.detect_contract_interfaces(checksum) if is_contract else [],
            "proxy_hints": self.read_proxy_hints(checksum) if is_contract else self._empty_proxy_hints(),
        }
        payload["token_hints"] = self._inspect_token_like(checksum, payload["detected_interfaces"], include_holder=False)
        return payload

    def inspect_contract(self, address: str) -> dict[str, Any]:
        payload = self.inspect_address(address)
        payload["token_hints"] = self._inspect_token_like(
            payload["address"],
            payload["detected_interfaces"],
            include_holder=False,
        )
        return payload

    def inspect_token(self, address: str, holder: str | None = None) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(address)
        code_size = self.get_code_size(checksum)
        interfaces = self.detect_contract_interfaces(checksum) if code_size > 0 else []
        token_payload = self._inspect_token_like(checksum, interfaces, include_holder=bool(holder), holder=holder)
        token_payload.update(
            {
                "address": checksum,
                "is_contract": code_size > 0,
                "code_size_bytes": code_size,
                "detected_interfaces": interfaces,
                "proxy_hints": self.read_proxy_hints(checksum) if code_size > 0 else self._empty_proxy_hints(),
            }
        )
        return token_payload

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
        elif payload["asset_type"] == "erc20_approval":
            payload["summary"] = f"Submitted ERC-20 approval on {self.network['name']}"
        elif payload["asset_type"] == "contract":
            payload["summary"] = f"Submitted contract write on {self.network['name']}"
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

    def _contract(self, address: str, abi: list[dict[str, Any]]):
        checksum = self.w3.to_checksum_address(address)
        return self.w3.eth.contract(address=checksum, abi=abi)

    def _result_type_hint(self, abi: list[dict[str, Any]], function_name: str) -> str | list[str] | None:
        for entry in abi:
            if entry.get("type") != "function" or entry.get("name") != function_name:
                continue
            outputs = entry.get("outputs") or []
            if not outputs:
                return None
            if len(outputs) == 1:
                return outputs[0].get("type")
            return [output.get("type") for output in outputs]
        return None

    def _read_storage_address(self, address: str, slot: int) -> str | None:
        try:
            raw = self.w3.eth.get_storage_at(self.w3.to_checksum_address(address), slot)
        except Exception:  # pragma: no cover - provider specific
            return None
        hex_value = prefixed_hex(raw)
        if hex_value == "0x" or int(hex_value, 16) == 0:
            return None
        candidate = f"0x{hex_value[-40:]}"
        if int(candidate, 16) == 0:
            return None
        return self.w3.to_checksum_address(candidate)

    def _safe_token_text(self, address: str, function_name: str, abi: list[dict[str, Any]]) -> str | None:
        value = self.safe_contract_call(address, abi, function_name)
        if isinstance(value, str):
            stripped = value.strip("\x00").strip()
            return stripped or None
        if isinstance(value, (bytes, bytearray)):
            decoded = bytes(value).rstrip(b"\x00").decode("utf-8", errors="ignore").strip()
            return decoded or None
        return None

    def _safe_token_name(self, address: str, standard_abi: list[dict[str, Any]]) -> str | None:
        return self._safe_token_text(address, "name", standard_abi) or self._safe_token_text(
            address,
            "name",
            ERC20_METADATA_BYTES32_ABI,
        )

    def _safe_token_symbol(self, address: str, standard_abi: list[dict[str, Any]]) -> str | None:
        return self._safe_token_text(address, "symbol", standard_abi) or self._safe_token_text(
            address,
            "symbol",
            ERC20_METADATA_BYTES32_ABI,
        )

    def _detect_erc20(self, address: str) -> bool:
        decimals = self.safe_contract_call(address, ERC20_ABI, "decimals")
        total_supply = self.safe_contract_call(address, ERC20_ABI, "totalSupply")
        balance = self.safe_contract_call(address, ERC20_ABI, "balanceOf", ZERO_ADDRESS)
        name = self._safe_token_name(address, ERC20_ABI)
        symbol = self._safe_token_symbol(address, ERC20_ABI)
        evidence = sum(
            1
            for value in (decimals, total_supply, balance, name, symbol)
            if value not in (None, "", b"")
        )
        return evidence >= 2 and (decimals is not None or balance is not None or total_supply is not None)

    def _inspect_token_like(
        self,
        address: str,
        interfaces: list[str],
        include_holder: bool,
        holder: str | None = None,
    ) -> dict[str, Any]:
        token_standard = "unknown"
        if "erc1155" in interfaces:
            token_standard = "erc1155"
        elif "erc721" in interfaces:
            token_standard = "erc721"
        elif "erc20" in interfaces:
            token_standard = "erc20"

        name: str | None = None
        symbol: str | None = None
        decimals: int | None = None
        total_supply: str | None = None
        metadata_uri: str | None = None

        if token_standard == "erc20":
            name = self._safe_token_name(address, ERC20_ABI)
            symbol = self._safe_token_symbol(address, ERC20_ABI)
            raw_decimals = self.safe_contract_call(address, ERC20_ABI, "decimals")
            decimals = int(raw_decimals) if raw_decimals is not None else None
            raw_total_supply = self.safe_contract_call(address, ERC20_ABI, "totalSupply")
            total_supply = str(int(raw_total_supply)) if raw_total_supply is not None else None
        elif token_standard == "erc721":
            name = self._safe_token_name(address, ERC721_ABI)
            symbol = self._safe_token_symbol(address, ERC721_ABI)
            raw_total_supply = self.safe_contract_call(address, ERC721_ABI, "totalSupply")
            total_supply = str(int(raw_total_supply)) if raw_total_supply is not None else None
        elif token_standard == "erc1155":
            metadata_uri = self.safe_contract_call(address, ERC1155_ABI, "uri", 0)
            if metadata_uri is not None:
                metadata_uri = str(metadata_uri)

        payload: dict[str, Any] = {
            "token_standard": token_standard,
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": total_supply,
            "metadata_uri": metadata_uri,
        }
        if include_holder and holder:
            payload["holder"] = self._inspect_holder_balance(address, token_standard, holder, decimals)
        return payload

    def _inspect_holder_balance(
        self,
        token_address: str,
        token_standard: str,
        holder: str,
        decimals: int | None,
    ) -> dict[str, Any]:
        checksum = self.w3.to_checksum_address(holder)
        payload: dict[str, Any] = {
            "address": checksum,
            "balance_lookup_supported": token_standard in {"erc20", "erc721"},
            "balance_raw": None,
            "balance": None,
            "note": None,
        }
        if token_standard == "erc20":
            raw_balance = self.safe_contract_call(token_address, ERC20_ABI, "balanceOf", checksum)
            if raw_balance is not None:
                payload["balance_raw"] = str(int(raw_balance))
                payload["balance"] = format_units(int(raw_balance), decimals or 0)
            return payload
        if token_standard == "erc721":
            raw_balance = self.safe_contract_call(token_address, ERC721_ABI, "balanceOf", checksum)
            if raw_balance is not None:
                payload["balance_raw"] = str(int(raw_balance))
                payload["balance"] = str(int(raw_balance))
            return payload
        if token_standard == "erc1155":
            payload["note"] = "ERC-1155 holder balances require a token id and are not included in v1 lookups."
            return payload
        payload["note"] = "Holder balance is unavailable because the target is not a detected token contract."
        return payload

    def _empty_proxy_hints(self) -> dict[str, Any]:
        return {
            "implementation": None,
            "admin": None,
            "beacon": None,
            "is_proxy": False,
        }

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


def parse_units_allow_zero(value: str, decimals: int) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"Invalid decimal amount: {value}") from exc
    if amount < 0:
        raise ValidationError("Amount must be zero or greater.")
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


def normalize_contract_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return prefixed_hex(value)
    if isinstance(value, bytearray):
        return prefixed_hex(bytes(value))
    if isinstance(value, tuple):
        return [normalize_contract_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_contract_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_contract_value(item) for key, item in value.items()}
    return value


def redact_rpc_url(url: str) -> str:
    parsed = urlsplit(url)
    netloc = parsed.netloc
    if "@" in netloc:
        _, hostinfo = netloc.rsplit("@", 1)
        netloc = hostinfo

    query = parsed.query
    if parsed.query:
        pairs = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.lower()
            if any(token in lowered for token in ("key", "token", "secret", "password", "auth", "signature")):
                pairs.append((key, "***"))
            else:
                pairs.append((key, value))
        query = urlencode(pairs, doseq=True)

    path = parsed.path
    if parsed.path:
        parts = parsed.path.rstrip("/").split("/")
        if parts and len(parts[-1]) >= 8:
            parts[-1] = "***"
            path = "/".join(parts)

    return urlunsplit((parsed.scheme, netloc, path, query, parsed.fragment))
