from __future__ import annotations

from typing import Any

from vault.config import ValidationError
from vault.evm import EVMClient
from vault.http import http_get_json, http_post_json
from vault.signers import resolve_signer


SAFE_ABI = [
    {
        "inputs": [],
        "name": "getOwners",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getThreshold",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nonce",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"internalType": "uint8", "name": "operation", "type": "uint8"},
            {"internalType": "uint256", "name": "safeTxGas", "type": "uint256"},
            {"internalType": "uint256", "name": "baseGas", "type": "uint256"},
            {"internalType": "uint256", "name": "gasPrice", "type": "uint256"},
            {"internalType": "address", "name": "gasToken", "type": "address"},
            {"internalType": "address", "name": "refundReceiver", "type": "address"},
            {"internalType": "uint256", "name": "_nonce", "type": "uint256"},
        ],
        "name": "getTransactionHash",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"internalType": "uint8", "name": "operation", "type": "uint8"},
            {"internalType": "uint256", "name": "safeTxGas", "type": "uint256"},
            {"internalType": "uint256", "name": "baseGas", "type": "uint256"},
            {"internalType": "uint256", "name": "gasPrice", "type": "uint256"},
            {"internalType": "address", "name": "gasToken", "type": "address"},
            {"internalType": "address", "name": "refundReceiver", "type": "address"},
            {"internalType": "bytes", "name": "signatures", "type": "bytes"},
        ],
        "name": "execTransaction",
        "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
        "stateMutability": "payable",
        "type": "function",
    },
]

SAFE_OWNER_MANAGER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "prevOwner", "type": "address"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "_threshold", "type": "uint256"},
        ],
        "name": "removeOwner",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "_threshold", "type": "uint256"},
        ],
        "name": "addOwnerWithThreshold",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "_threshold", "type": "uint256"}],
        "name": "changeThreshold",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

SAFE_SETUP_ABI = [
    {
        "inputs": [
            {"internalType": "address[]", "name": "_owners", "type": "address[]"},
            {"internalType": "uint256", "name": "_threshold", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"internalType": "address", "name": "fallbackHandler", "type": "address"},
            {"internalType": "address", "name": "paymentToken", "type": "address"},
            {"internalType": "uint256", "name": "payment", "type": "uint256"},
            {"internalType": "address payable", "name": "paymentReceiver", "type": "address"},
        ],
        "name": "setup",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

SAFE_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "_singleton", "type": "address"},
            {"internalType": "bytes", "name": "initializer", "type": "bytes"},
            {"internalType": "uint256", "name": "saltNonce", "type": "uint256"},
        ],
        "name": "createProxyWithNonce",
        "outputs": [{"internalType": "address", "name": "proxy", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

SAFE_TRANSACTION_SENTINEL = "0x0000000000000000000000000000000000000001"


class SafeClient:
    def __init__(self, network: dict[str, Any], service_url: str | None = None) -> None:
        self.network = network
        self.evm = EVMClient(network)
        self.w3 = self.evm.w3
        self.service_url = service_url.rstrip("/") if service_url else None

    def get_safe_info(self, safe_address: str) -> dict[str, Any]:
        safe = self._safe_contract(safe_address)
        owners = [self.w3.to_checksum_address(owner) for owner in safe.functions.getOwners().call()]
        threshold = int(safe.functions.getThreshold().call())
        nonce = int(safe.functions.nonce().call())
        info = {
            "address": self.w3.to_checksum_address(safe_address),
            "network": self.network["name"],
            "chain_id": self.network["chain_id"],
            "owners": owners,
            "threshold": threshold,
            "nonce": nonce,
        }
        if self.service_url:
            try:
                service_info = self._service_get(f"/v1/safes/{info['address']}/")
                info["service_info"] = service_info
            except ValidationError:
                info["service_info"] = None
        return info

    def list_pending_transactions(self, safe_address: str) -> dict[str, Any]:
        self._require_service()
        payload = self._service_get(f"/v1/safes/{self.w3.to_checksum_address(safe_address)}/multisig-transactions/?executed=false")
        results = payload.get("results", payload if isinstance(payload, list) else [])
        return {
            "summary": f"Found {len(results)} Safe pending transaction(s)",
            "transactions": results,
            "count": len(results),
        }

    def get_pending_transaction(self, safe_tx_hash: str) -> dict[str, Any]:
        self._require_service()
        payload = self._service_get(f"/v1/multisig-transactions/{safe_tx_hash}/")
        payload["summary"] = f"Pending Safe transaction {safe_tx_hash}"
        return payload

    def propose_transaction(
        self,
        safe_config: dict[str, Any],
        signer_paths: Any,
        proposer_metadata: dict[str, Any],
        passphrase: str,
        to: str,
        value_wei: int,
        data: str,
        operation: int = 0,
        safe_tx_gas: int = 0,
        base_gas: int = 0,
        gas_price: int = 0,
        gas_token: str = "0x0000000000000000000000000000000000000000",
        refund_receiver: str = "0x0000000000000000000000000000000000000000",
        nonce: int | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        self._require_service()
        safe_address = self.w3.to_checksum_address(safe_config["address"])
        tx_nonce = nonce if nonce is not None else self.get_safe_info(safe_address)["nonce"]
        safe_tx_hash = self.compute_safe_tx_hash(
            safe_address=safe_address,
            to=to,
            value_wei=value_wei,
            data=data,
            operation=operation,
            safe_tx_gas=safe_tx_gas,
            base_gas=base_gas,
            gas_price=gas_price,
            gas_token=gas_token,
            refund_receiver=refund_receiver,
            nonce=tx_nonce,
        )
        signer = resolve_signer(signer_paths, proposer_metadata)
        signature = sign_safe_hash(signer, passphrase, safe_tx_hash)
        tx_data = {
            "to": self.w3.to_checksum_address(to),
            "value": str(value_wei),
            "data": data,
            "operation": operation,
            "safeTxGas": str(safe_tx_gas),
            "baseGas": str(base_gas),
            "gasPrice": str(gas_price),
            "gasToken": self.w3.to_checksum_address(gas_token),
            "refundReceiver": self.w3.to_checksum_address(refund_receiver),
            "nonce": str(tx_nonce),
        }
        payload = {
            "safeAddress": safe_address,
            "safeTxHash": safe_tx_hash,
            "safeTransactionData": tx_data,
            "senderAddress": proposer_metadata["address"],
            "senderSignature": signature,
        }
        if origin:
            payload["origin"] = origin
        response = self._service_post(f"/v1/safes/{safe_address}/multisig-transactions/", payload)
        return {
            "summary": f"Proposed Safe transaction {safe_tx_hash}",
            "safe_tx_hash": safe_tx_hash,
            "network": self.network["name"],
            "safe_address": safe_address,
            "nonce": tx_nonce,
            "proposal": response,
        }

    def confirm_transaction(
        self,
        signer_paths: Any,
        signer_metadata: dict[str, Any],
        passphrase: str,
        safe_tx_hash: str,
    ) -> dict[str, Any]:
        self._require_service()
        signer = resolve_signer(signer_paths, signer_metadata)
        signature = sign_safe_hash(signer, passphrase, safe_tx_hash)
        response = self._service_post(
            f"/v1/multisig-transactions/{safe_tx_hash}/confirmations/",
            {"signature": signature},
        )
        return {
            "summary": f"Confirmed Safe transaction {safe_tx_hash}",
            "safe_tx_hash": safe_tx_hash,
            "signer": signer_metadata["name"],
            "signature": signature,
            "confirmation": response,
        }

    def execute_transaction(
        self,
        safe_config: dict[str, Any],
        signer_paths: Any,
        signer_metadata: dict[str, Any],
        passphrase: str,
        safe_tx_hash: str,
    ) -> dict[str, Any]:
        pending = self.get_pending_transaction(safe_tx_hash)
        safe_address = self.w3.to_checksum_address(safe_config["address"])
        signatures = build_signature_bytes(pending.get("confirmations") or [])
        exec_contract = self._safe_contract(safe_address)
        tx = exec_contract.functions.execTransaction(
            self.w3.to_checksum_address(pending["to"]),
            int(pending["value"]),
            bytes.fromhex(strip_0x(pending["data"])),
            int(pending["operation"]),
            int(pending.get("safeTxGas", 0)),
            int(pending.get("baseGas", 0)),
            int(pending.get("gasPrice", 0)),
            self.w3.to_checksum_address(pending.get("gasToken") or "0x0000000000000000000000000000000000000000"),
            self.w3.to_checksum_address(pending.get("refundReceiver") or "0x0000000000000000000000000000000000000000"),
            signatures,
        ).build_transaction(
            {
                "chainId": self.network["chain_id"],
                "from": self.w3.to_checksum_address(signer_metadata["address"]),
                "nonce": self.evm.w3.eth.get_transaction_count(self.w3.to_checksum_address(signer_metadata["address"])),
            }
        )
        tx["gas"] = self.evm.w3.eth.estimate_gas(tx)
        tx.update(self.evm._resolve_fee_fields(None, None, None))
        signer = resolve_signer(signer_paths, signer_metadata)
        preview = {
            "tx": tx,
            "asset_type": "native",
            "symbol": self.network["symbol"],
            "from_address": signer_metadata["address"],
            "to_address": safe_address,
            "account_name": signer_metadata["name"],
        }
        payload = signer.send_prepared(passphrase, preview, self.network)
        payload["summary"] = f"Executed Safe transaction {safe_tx_hash}"
        payload["safe_tx_hash"] = safe_tx_hash
        payload["safe_address"] = safe_address
        return payload

    def create_safe(
        self,
        signer_paths: Any,
        signer_metadata: dict[str, Any],
        passphrase: str,
        singleton: str,
        factory: str,
        fallback_handler: str,
        owners: list[str],
        threshold: int,
        salt_nonce: int,
    ) -> dict[str, Any]:
        setup_contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(singleton),
            abi=SAFE_SETUP_ABI,
        )
        initializer = setup_contract.encode_abi(
            "setup",
            args=[
                [self.w3.to_checksum_address(owner) for owner in owners],
                threshold,
                self.w3.to_checksum_address("0x0000000000000000000000000000000000000000"),
                b"",
                self.w3.to_checksum_address(fallback_handler),
                self.w3.to_checksum_address("0x0000000000000000000000000000000000000000"),
                0,
                self.w3.to_checksum_address("0x0000000000000000000000000000000000000000"),
            ],
        )
        factory_contract = self.w3.eth.contract(address=self.w3.to_checksum_address(factory), abi=SAFE_FACTORY_ABI)
        tx = factory_contract.functions.createProxyWithNonce(
            self.w3.to_checksum_address(singleton),
            bytes.fromhex(strip_0x(initializer)),
            salt_nonce,
        ).build_transaction(
            {
                "chainId": self.network["chain_id"],
                "from": self.w3.to_checksum_address(signer_metadata["address"]),
                "nonce": self.evm.w3.eth.get_transaction_count(self.w3.to_checksum_address(signer_metadata["address"])),
            }
        )
        tx["gas"] = self.evm.w3.eth.estimate_gas(tx)
        tx.update(self.evm._resolve_fee_fields(None, None, None))
        signer = resolve_signer(signer_paths, signer_metadata)
        preview = {
            "tx": tx,
            "asset_type": "native",
            "symbol": self.network["symbol"],
            "from_address": signer_metadata["address"],
            "to_address": self.w3.to_checksum_address(factory),
            "account_name": signer_metadata["name"],
        }
        payload = signer.send_prepared(passphrase, preview, self.network)
        payload["summary"] = "Submitted Safe create transaction"
        payload["singleton"] = self.w3.to_checksum_address(singleton)
        payload["factory"] = self.w3.to_checksum_address(factory)
        payload["salt_nonce"] = salt_nonce
        return payload

    def encode_add_owner(self, owner: str, threshold: int) -> str:
        contract = self.w3.eth.contract(address=self.w3.to_checksum_address("0x0000000000000000000000000000000000000001"), abi=SAFE_OWNER_MANAGER_ABI)
        return contract.encode_abi("addOwnerWithThreshold", args=[self.w3.to_checksum_address(owner), threshold])

    def encode_remove_owner(self, prev_owner: str, owner: str, threshold: int) -> str:
        contract = self.w3.eth.contract(address=self.w3.to_checksum_address("0x0000000000000000000000000000000000000001"), abi=SAFE_OWNER_MANAGER_ABI)
        return contract.encode_abi(
            "removeOwner",
            args=[self.w3.to_checksum_address(prev_owner), self.w3.to_checksum_address(owner), threshold],
        )

    def encode_change_threshold(self, threshold: int) -> str:
        contract = self.w3.eth.contract(address=self.w3.to_checksum_address("0x0000000000000000000000000000000000000001"), abi=SAFE_OWNER_MANAGER_ABI)
        return contract.encode_abi("changeThreshold", args=[threshold])

    def compute_safe_tx_hash(
        self,
        safe_address: str,
        to: str,
        value_wei: int,
        data: str,
        operation: int,
        safe_tx_gas: int,
        base_gas: int,
        gas_price: int,
        gas_token: str,
        refund_receiver: str,
        nonce: int,
    ) -> str:
        safe = self._safe_contract(safe_address)
        tx_hash = safe.functions.getTransactionHash(
            self.w3.to_checksum_address(to),
            int(value_wei),
            bytes.fromhex(strip_0x(data)),
            int(operation),
            int(safe_tx_gas),
            int(base_gas),
            int(gas_price),
            self.w3.to_checksum_address(gas_token),
            self.w3.to_checksum_address(refund_receiver),
            int(nonce),
        ).call()
        return prefixed_hex(tx_hash)

    def _safe_contract(self, safe_address: str):
        return self.w3.eth.contract(address=self.w3.to_checksum_address(safe_address), abi=SAFE_ABI)

    def _service_get(self, path: str) -> Any:
        self._require_service()
        return http_get_json(f"{self.service_url}{path}")

    def _service_post(self, path: str, payload: Any) -> Any:
        self._require_service()
        return http_post_json(f"{self.service_url}{path}", payload)

    def _require_service(self) -> None:
        if not self.service_url:
            raise ValidationError("This Safe operation requires a Safe Transaction Service URL.")


class SafeClientError(ValidationError):
    pass


def sign_safe_hash(signer: Any, passphrase: str, safe_tx_hash: str) -> str:
    from eth_account import Account

    signer.ensure_can_sign()
    if not hasattr(signer, "accounts"):
        raise ValidationError("Safe signing currently requires a local signer account.")
    unlocked = signer.accounts.unlock_account(signer.name, passphrase)
    signed = Account.unsafe_sign_hash(bytes.fromhex(strip_0x(safe_tx_hash)), unlocked.private_key_hex)
    return prefixed_hex(signed.signature)


def build_signature_bytes(confirmations: list[dict[str, Any]]) -> bytes:
    from web3 import Web3

    entries = []
    for item in confirmations:
        owner = Web3.to_checksum_address(item["owner"])
        signature = item.get("signature")
        if not signature:
            continue
        entries.append((owner.lower(), bytes.fromhex(strip_0x(signature))))
    entries.sort(key=lambda item: item[0])
    return b"".join(signature for _, signature in entries)


def strip_0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def prefixed_hex(value: Any) -> str:
    if hasattr(value, "hex"):
        raw = value.hex()
    else:
        raw = str(value)
    return raw if raw.startswith("0x") else f"0x{raw}"
