# vault

`vault` is a local-first EVM wallet CLI and TUI.

It manages accounts, networks, signing, sending, policy checks, journal storage, and smart-account workflows without turning into a general-purpose web3 automation platform.

## What It Does

- stores local signer keys in encrypted keystore files
- supports watch-only accounts
- separates `dev`, `test`, and `prod` profiles
- supports Alchemy presets, custom RPCs, and local Anvil networks
- fetches native and ERC-20 balances
- signs messages and EIP-712 typed data
- previews, simulates, signs, and broadcasts EOA transactions
- applies outbound policy rules before protected actions
- records local journal entries and receipts
- registers Safe and ERC-4337 smart-account configs
- provides a Textual TUI for daily terminal use

## What It Does Not Do

- it is not a chain indexer
- it is not a bot runner or workflow engine
- it is not portfolio or tax software
- it is not a substitute for a hardware wallet for larger funds
- it does not yet have live-validated Safe and ERC-4337 backend coverage for every provider combination

## Install

```bash
pip install -e .
```

## Safety Model

Profiles:

- `dev`: local Anvil and disposable development work
- `test`: public testnets like Sepolia
- `prod`: real funds and intentional live actions

Rules:

- keep real funds in `prod`
- do daily development in `dev`
- use `test` for public testnet integration
- do not point the TUI at `prod` unless you mean to
- use `vault safety status` before changing a mixed store

Important:

- existing legacy wallets under `~/.vault` are treated as `prod`
- `vault` does not move legacy stores automatically
- strong confirmation is required for protected send paths

## Storage

By default, `vault` stores data under `~/.vault`.

Each profile has its own store for:

- accounts
- networks
- address book
- policy
- journal
- smart-account registry
- theme

You can override the root with `VAULT_HOME`:

```bash
export VAULT_HOME="$PWD/.vault-test"
```

## Quick Start

Alchemy:

```bash
export ALCHEMY_API_KEY="your-api-key"

vault network list-presets
vault network add-alchemy --preset eth-sepolia --name sepolia --set-default
vault doctor --network sepolia

vault account create --name main --set-default
vault balance --account main --network sepolia
```

Local Anvil:

```bash
vault profile use --name dev
anvil

vault network add-anvil --name local --set-default
vault account import --name local-dev --private-key 0xANVIL_PRIVATE_KEY --set-default

vault doctor --network local
vault balance --account local-dev --network local
vault send --from-account local-dev --network local --to 0xANVIL_ADDRESS --amount 1
```

## Core Commands

Profiles:

```bash
vault profile list
vault profile show
vault profile use --name dev
vault safety status
```

Accounts:

```bash
vault account create --name main --set-default
vault account import --name signer --private-key 0x...
vault account watch --name treasury-observer --address 0xabc...
vault account list
vault account use --name main
```

Networks:

```bash
vault network list-presets
vault network add-alchemy --preset eth-mainnet --name mainnet
vault network add-anvil --name local --set-default
vault network add --name custom --rpc-url https://rpc.example --chain-id 1 --symbol ETH
vault network list
```

Address book:

```bash
vault address-book add --name faucet --address 0xabc... --network sepolia
vault address-book list
vault address-book remove --name faucet
```

Balances and send:

```bash
vault balance --account main --network mainnet
vault simulate --from-account main --network sepolia --to faucet --amount 0.01
vault send --from-account main --network sepolia --to faucet --amount 0.01
```

Signing:

```bash
vault sign-message --account main --message "hello from vault"
vault sign-typed-data --account main --file typed-data.json
```

Policy and journal:

```bash
vault policy list
vault policy show
vault policy set --rule blocked_networks --value mainnet
vault policy explain --account main --network sepolia --to faucet --amount 0.01

vault backup verify --account main
vault journal list
vault journal show --tx-hash 0x...
vault receipt show --tx-hash 0x...
```

## Smart Accounts

Safe:

```bash
vault safe register \
  --name team-safe \
  --address 0xabc... \
  --network mainnet \
  --service-url https://safe-transaction-mainnet.safe.global

vault smart-account list
vault smart-account show --name team-safe
vault safe pending --name team-safe
vault safe tx --name team-safe --safe-tx-hash 0x...
```

ERC-4337:

```bash
vault aa register \
  --name session-account \
  --sender 0xabc... \
  --network sepolia \
  --owner-account main \
  --entrypoint 0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789 \
  --bundler-url https://your-bundler.example

vault aa prepare --name session-account --to 0xdef... --value 0 --data 0x
```

Current boundary:

- Safe config and workflow support is built in
- ERC-4337 config and user-operation workflow support is built in
- those paths still need real-endpoint validation in your environment before you should trust them with production operations

## TUI

Launch:

```bash
vault ui
vault ui --profile dev
```

Current TUI areas:

- profiles
- accounts
- networks
- address book
- balance
- send
- smart-account registry
- policy inspection and editing
- journal inspection and receipt lookup
- smart-account ops for Safe and ERC-4337

## Repository Hygiene

Never commit:

- wallet stores like `.vault`, `.vault-test`, or backups
- `.env` files
- API keys
- private keys
- local bundler or service URLs that embed credentials

The repo `.gitignore` is configured to keep local wallet state, backups, env files, and venvs out of git.

## Known Limits

- no hardware-wallet integration yet
- no Safe SDK dependency; Safe service and on-chain flows are implemented directly
- no full provider matrix testing for ERC-4337
- no bot, scheduler, or automation engine
- no chain-wide analytics or portfolio indexing

## Audit Status

Verified in this repo:

- unit test suite passes
- package installs with `pip install -e .`
- local Anvil flow works end to end:
  - account import
  - RPC health check
  - balance lookup
  - transaction simulation
  - real local send
  - journal write
  - receipt lookup

Fixed during audit:

- Safe owner checks now compare owner addresses correctly
- transaction hashes are normalized before journal storage
- receipt hashes keep the `0x` prefix
- signed hashes and signatures are emitted in normalized `0x` form
- repo ignore rules now cover local wallet stores and env files

Still treat as provisional until you validate them live:

- Safe proposal / confirm / execute against your chosen Safe Transaction Service
- ERC-4337 prepare / sign / simulate / submit / status against your chosen bundler

Current known risks:

- smart-account service and bundler URLs are stored and displayed as entered, so do not paste credential-bearing URLs
- HTTP requests for Safe and ERC-4337 backends do not yet set explicit timeouts

## Publish Checklist

Before the first real commit or push:

1. Run `git status --short --ignored` and confirm wallet stores are ignored.
2. Confirm `.vault*`, `.env*`, and `venv/` are not staged.
3. Do not commit any local wallet home or backup directory.
4. Keep API keys in environment variables, not config files.
5. Prefer `dev` or `test` for screenshots, demos, and recordings.

## Recommended Workflow

1. Build and debug in `dev` with Anvil.
2. Validate hosted RPC behavior in `test`.
3. Use `prod` only for intentional real-fund operations.
4. Keep wallet homes and backups out of git.
