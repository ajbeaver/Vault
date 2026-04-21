from __future__ import annotations

from typing import Any

from vault.config import ValidationError
from vault.evm import EVMClient
from vault.signers import resolve_signer


ENTRYPOINT_V06 = "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789"


class ERC4337Client:
    def __init__(self, network: dict[str, Any], config: dict[str, Any], signer_paths: Any) -> None:
        self.network = network
        self.config = config
        self.signer_paths = signer_paths
        self.evm = EVMClient(network)
        self.w3 = self.evm.w3

    def prepare_user_operation(
        self,
        to: str,
        data: str = "0x",
        value_wei: int = 0,
        nonce: str | None = None,
        signature: str | None = None,
        init_code: str | None = None,
        paymaster_and_data: str | None = None,
    ) -> dict[str, Any]:
        user_op = {
            "sender": self.w3.to_checksum_address(self.config["address"]),
            "nonce": nonce or "0x0",
            "initCode": init_code or self._build_init_code(),
            "callData": self._encode_execute(self.w3.to_checksum_address(to), value_wei, data),
            "callGasLimit": "0x0",
            "verificationGasLimit": "0x0",
            "preVerificationGas": "0x0",
            "maxFeePerGas": hex(int(self.w3.eth.gas_price)),
            "maxPriorityFeePerGas": self._max_priority_fee_hex(),
            "paymasterAndData": paymaster_and_data or "0x",
            "signature": signature or "0x",
        }
        gas = self._rpc("eth_estimateUserOperationGas", [user_op, self._entrypoint()])
        user_op["callGasLimit"] = gas["callGasLimit"]
        user_op["verificationGasLimit"] = gas["verificationGasLimit"]
        user_op["preVerificationGas"] = gas["preVerificationGas"]

        return {
            "summary": f"Prepared user operation for {self.config['name']}",
            "smart_account": self.config["name"],
            "network": self.network["name"],
            "entrypoint": self._entrypoint(),
            "user_operation": user_op,
        }

    def sign_user_operation(self, user_operation: dict[str, Any], passphrase: str) -> dict[str, Any]:
        if self.config.get("signature_mode") != "userop_hash_v06_eoa":
            raise ValidationError("Automatic signing is not available for this ERC-4337 account configuration.")
        from eth_account import Account

        signer_metadata = self._owner_metadata()
        signer = resolve_signer(self.signer_paths, signer_metadata)
        if not hasattr(signer, "accounts"):
            raise ValidationError("ERC-4337 signing currently requires a local signer account.")
        unlocked = signer.accounts.unlock_account(signer.name, passphrase)
        signature_hash = user_operation_hash_v06(user_operation, self._entrypoint(), self.network["chain_id"])
        signed = Account.unsafe_sign_hash(signature_hash, unlocked.private_key_hex)
        payload = dict(user_operation)
        payload["signature"] = prefixed_hex(signed.signature)
        return {
            "summary": f"Signed user operation for {self.config['name']}",
            "smart_account": self.config["name"],
            "network": self.network["name"],
            "entrypoint": self._entrypoint(),
            "user_operation_hash": prefixed_hex(signature_hash),
            "user_operation": payload,
            "signature": payload["signature"],
        }

    def simulate_user_operation(self, user_operation: dict[str, Any]) -> dict[str, Any]:
        gas = self._rpc("eth_estimateUserOperationGas", [user_operation, self._entrypoint()])
        return {
            "summary": f"Simulated user operation for {self.config['name']}",
            "smart_account": self.config["name"],
            "network": self.network["name"],
            "entrypoint": self._entrypoint(),
            "status": "success",
            "gas": gas,
            "user_operation": user_operation,
        }

    def submit_user_operation(self, user_operation: dict[str, Any]) -> dict[str, Any]:
        user_op_hash = self._rpc("eth_sendUserOperation", [user_operation, self._entrypoint()])
        if isinstance(user_op_hash, dict) and "result" in user_op_hash:
            user_op_hash = user_op_hash["result"]
        return {
            "summary": f"Submitted user operation for {self.config['name']}",
            "smart_account": self.config["name"],
            "network": self.network["name"],
            "entrypoint": self._entrypoint(),
            "user_operation_hash": user_op_hash,
            "user_operation": user_operation,
        }

    def get_user_operation_status(self, user_op_hash: str) -> dict[str, Any]:
        receipt = self._rpc("eth_getUserOperationReceipt", [user_op_hash])
        operation = self._rpc("eth_getUserOperationByHash", [user_op_hash])
        return {
            "summary": f"User operation status for {user_op_hash}",
            "smart_account": self.config["name"],
            "network": self.network["name"],
            "entrypoint": self._entrypoint(),
            "user_operation_hash": user_op_hash,
            "user_operation": operation,
            "receipt": receipt,
        }

    def _rpc(self, method: str, params: list[Any]) -> Any:
        response = self.evm.w3.provider.make_request(method, params)
        if "error" in response:
            raise ValidationError(f"{method} failed: {response['error']}")
        return response.get("result")

    def _entrypoint(self) -> str:
        return self.config.get("entrypoint") or ENTRYPOINT_V06

    def _build_init_code(self) -> str:
        factory = self.config.get("factory")
        factory_data = self.config.get("factory_data") or "0x"
        if not factory:
            return "0x"
        return self.w3.to_checksum_address(factory) + strip_0x(factory_data)

    def _encode_execute(self, to: str, value_wei: int, data: str) -> str:
        from eth_abi import encode
        from eth_utils import keccak

        selector = keccak(text="execute(address,uint256,bytes)")[:4]
        encoded = encode(["address", "uint256", "bytes"], [to, int(value_wei), bytes.fromhex(strip_0x(data))])
        return "0x" + (selector + encoded).hex()

    def _max_priority_fee_hex(self) -> str:
        try:
            return hex(int(self.w3.eth.max_priority_fee))
        except Exception:  # pragma: no cover - provider specific
            return hex(self.w3.to_wei(2, "gwei"))

    def _owner_metadata(self) -> dict[str, Any]:
        from vault.keystore import KeystoreManager

        return KeystoreManager(self.signer_paths).get_account_metadata(self.config["owner_account"])


def user_operation_hash_v06(user_op: dict[str, Any], entrypoint: str, chain_id: int) -> bytes:
    from eth_abi import encode
    from eth_utils import keccak

    user_op_typehash = keccak(
        text="UserOperation(address sender,uint256 nonce,bytes initCode,bytes callData,uint256 callGasLimit,uint256 verificationGasLimit,uint256 preVerificationGas,uint256 maxFeePerGas,uint256 maxPriorityFeePerGas,bytes paymasterAndData)"
    )
    packed = encode(
        [
            "bytes32",
            "address",
            "uint256",
            "bytes32",
            "bytes32",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            user_op_typehash,
            user_op["sender"],
            int(user_op["nonce"], 16),
            keccak(bytes.fromhex(strip_0x(user_op["initCode"]))),
            keccak(bytes.fromhex(strip_0x(user_op["callData"]))),
            int(user_op["callGasLimit"], 16),
            int(user_op["verificationGasLimit"], 16),
            int(user_op["preVerificationGas"], 16),
            int(user_op["maxFeePerGas"], 16),
            int(user_op["maxPriorityFeePerGas"], 16),
            keccak(bytes.fromhex(strip_0x(user_op["paymasterAndData"]))),
        ],
    )
    user_op_hash = keccak(packed)
    return keccak(encode(["bytes32", "address", "uint256"], [user_op_hash, entrypoint, chain_id]))


def strip_0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def prefixed_hex(value: Any) -> str:
    if hasattr(value, "hex"):
        raw = value.hex()
    else:
        raw = str(value)
    return raw if raw.startswith("0x") else f"0x{raw}"
