from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from vault.address_book import normalize_address
from vault.config import ValidationError, VaultPaths, load_json, save_json
from vault.keystore import validate_name


POLICY_RULES = {
    "allowed_recipients",
    "blocked_recipients",
    "allowed_networks",
    "blocked_networks",
    "max_native_amount",
    "max_token_amounts",
    "require_simulation_on_protected",
}


class PolicyManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def list_policies(self) -> dict[str, Any]:
        payload = self._load()
        return {
            "summary": "Policy store",
            "defaults": payload["defaults"],
            "accounts": payload["accounts"],
        }

    def show_effective_policy(self, account_name: str | None = None) -> dict[str, Any]:
        effective = self.effective_policy(account_name)
        return {
            "summary": f"Effective policy for {account_name or 'profile'}",
            "scope": account_name or "profile",
            "policy": effective,
        }

    def set_rule(self, rule: str, value: str, account_name: str | None = None) -> dict[str, Any]:
        normalized_rule = normalize_rule(rule)
        payload = self._load()
        bucket = self._bucket(payload, account_name, create=True)
        bucket[normalized_rule] = parse_rule_value(normalized_rule, value)
        save_json(self.paths.policy_file, payload)
        return {
            "summary": f"Updated policy rule {normalized_rule}",
            "scope": account_name or "profile",
            "rule": normalized_rule,
            "value": bucket[normalized_rule],
        }

    def unset_rule(self, rule: str, account_name: str | None = None) -> dict[str, Any]:
        normalized_rule = normalize_rule(rule)
        payload = self._load()
        bucket = self._bucket(payload, account_name, create=False)
        bucket.pop(normalized_rule, None)
        save_json(self.paths.policy_file, payload)
        return {
            "summary": f"Removed policy rule {normalized_rule}",
            "scope": account_name or "profile",
            "rule": normalized_rule,
        }

    def effective_policy(self, account_name: str | None = None) -> dict[str, Any]:
        payload = self._load()
        effective = dict(default_policy())
        effective.update(payload["defaults"])
        if account_name:
            normalized = validate_name(account_name)
            effective.update(payload["accounts"].get(normalized, {}))
        return effective

    def evaluate_action(
        self,
        account_name: str,
        network_name: str,
        recipient_address: str,
        asset_type: str,
        amount: str,
        token_address: str | None = None,
        protected: bool = False,
    ) -> dict[str, Any]:
        policy = self.effective_policy(account_name)
        findings: list[str] = []
        allowed = True
        normalized_recipient = normalize_address(recipient_address)
        normalized_network = validate_name(network_name)

        if policy["allowed_networks"] and normalized_network not in policy["allowed_networks"]:
            allowed = False
            findings.append(f"Network `{normalized_network}` is not in the allowed network list.")
        if normalized_network in policy["blocked_networks"]:
            allowed = False
            findings.append(f"Network `{normalized_network}` is blocked by policy.")
        if policy["allowed_recipients"] and normalized_recipient not in policy["allowed_recipients"]:
            allowed = False
            findings.append(f"Recipient `{normalized_recipient}` is not in the allowed recipient list.")
        if normalized_recipient in policy["blocked_recipients"]:
            allowed = False
            findings.append(f"Recipient `{normalized_recipient}` is blocked by policy.")

        if asset_type == "native" and policy["max_native_amount"] is not None:
            if Decimal(amount) > Decimal(policy["max_native_amount"]):
                allowed = False
                findings.append(
                    f"Native amount {amount} exceeds policy max {policy['max_native_amount']}."
                )

        if asset_type == "erc20" and token_address:
            token_key = normalize_address(token_address)
            token_cap = policy["max_token_amounts"].get(token_key)
            if token_cap is not None and Decimal(amount) > Decimal(token_cap):
                allowed = False
                findings.append(f"Token amount {amount} exceeds policy max {token_cap} for {token_key}.")

        requires_simulation = bool(protected and policy["require_simulation_on_protected"])
        if not findings:
            findings.append("Action allowed by policy.")

        return {
            "summary": "Policy evaluation",
            "allowed": allowed,
            "requires_simulation": requires_simulation,
            "effective_policy": policy,
            "findings": findings,
        }

    def _load(self) -> dict[str, Any]:
        payload = load_json(self.paths.policy_file, None)
        if payload is None:
            return {
                "defaults": default_policy(),
                "accounts": {},
            }
        payload.setdefault("defaults", default_policy())
        payload.setdefault("accounts", {})
        for account_policy in payload["accounts"].values():
            merged = default_policy()
            merged.update(account_policy)
            account_policy.clear()
            account_policy.update(merged)
        merged_defaults = default_policy()
        merged_defaults.update(payload["defaults"])
        payload["defaults"] = merged_defaults
        return payload

    def _bucket(self, payload: dict[str, Any], account_name: str | None, create: bool) -> dict[str, Any]:
        if not account_name:
            return payload["defaults"]
        normalized = validate_name(account_name)
        if create:
            payload["accounts"].setdefault(normalized, default_policy())
        return payload["accounts"].setdefault(normalized, default_policy())


def default_policy() -> dict[str, Any]:
    return {
        "allowed_recipients": [],
        "blocked_recipients": [],
        "allowed_networks": [],
        "blocked_networks": [],
        "max_native_amount": None,
        "max_token_amounts": {},
        "require_simulation_on_protected": True,
    }


def normalize_rule(rule: str) -> str:
    normalized = rule.strip().lower()
    if normalized not in POLICY_RULES:
        raise ValidationError(f"Unknown policy rule `{rule}`.")
    return normalized


def parse_rule_value(rule: str, value: str) -> Any:
    raw = value.strip()
    if rule in {"allowed_recipients", "blocked_recipients"}:
        return [normalize_address(item) for item in split_csv(raw)]
    if rule in {"allowed_networks", "blocked_networks"}:
        return [validate_name(item) for item in split_csv(raw)]
    if rule == "max_native_amount":
        return parse_decimal(raw)
    if rule == "max_token_amounts":
        items = {}
        for item in split_csv(raw):
            if "=" not in item:
                raise ValidationError("Token amount policy entries must use ADDRESS=AMOUNT format.")
            token, amount = item.split("=", 1)
            items[normalize_address(token)] = parse_decimal(amount)
        return items
    if rule == "require_simulation_on_protected":
        return parse_bool(raw)
    raise ValidationError(f"Unsupported policy rule `{rule}`.")


def split_csv(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_decimal(raw: str) -> str:
    if not raw:
        raise ValidationError("Policy value cannot be empty.")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError("Policy amount must be a valid decimal value.") from exc
    if amount <= 0:
        raise ValidationError("Policy amount must be greater than zero.")
    return format(amount.normalize(), "f")


def parse_bool(raw: str) -> bool:
    normalized = raw.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValidationError("Boolean policy values must be one of true/false/yes/no/on/off.")
