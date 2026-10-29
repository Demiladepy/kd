"""Chain configuration tests. No network: ChainConfig + unit maths only."""

from decimal import Decimal, ROUND_DOWN

import pytest

from server.chain import ChainConfig, ChainConfigError, NATIVE_DECIMALS, USDC_DECIMALS

ENV = {
    "CHAIN_NAME": "arc-testnet",
    "CHAIN_ID": "5042002",
    "RPC_URL": "https://rpc.testnet.arc.network",
    "USDC_ADDRESS": "0x3600000000000000000000000000000000000000",
    "EXPLORER_TX_URL": "https://testnet.arcscan.app/tx/",
    "GAS_TOKEN_IS_USDC": "true",
}


def test_config_reads_from_env():
    cfg = ChainConfig.from_env(ENV)
    assert cfg.name == "arc-testnet"
    assert cfg.chain_id == 5042002
    assert cfg.gas_token_is_usdc is True
    assert cfg.usdc_address == "0x3600000000000000000000000000000000000000"


def test_gas_token_flag_defaults_to_false():
    env = dict(ENV)
    env.pop("GAS_TOKEN_IS_USDC")
    assert ChainConfig.from_env(env).gas_token_is_usdc is False


@pytest.mark.parametrize("flag,expected", [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False), ("0", False)])
def test_gas_token_flag_parsing(flag, expected):
    env = dict(ENV)
    env["GAS_TOKEN_IS_USDC"] = flag
    assert ChainConfig.from_env(env).gas_token_is_usdc is expected


@pytest.mark.parametrize("missing", ["CHAIN_ID", "RPC_URL", "USDC_ADDRESS", "EXPLORER_TX_URL"])
def test_missing_required_keys_raise(missing):
    env = dict(ENV)
    env.pop(missing)
    with pytest.raises(ChainConfigError) as exc:
        ChainConfig.from_env(env)
    assert missing in str(exc.value)


def test_non_integer_chain_id_raises():
    env = dict(ENV)
    env["CHAIN_ID"] = "arc"
    with pytest.raises(ChainConfigError) as exc:
        ChainConfig.from_env(env)
    assert "integer" in str(exc.value)


def test_invalid_usdc_address_raises():
    env = dict(ENV)
    env["USDC_ADDRESS"] = "0xnot-an-address"
    with pytest.raises(ChainConfigError):
        ChainConfig.from_env(env)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://testnet.arcscan.app/tx/", "https://testnet.arcscan.app/tx/"),
        ("https://testnet.arcscan.app/tx", "https://testnet.arcscan.app/tx/"),
    ],
)
def test_explorer_base_always_ends_with_slash(raw, expected):
    env = dict(ENV)
    env["EXPLORER_TX_URL"] = raw
    assert ChainConfig.from_env(env).explorer_base == expected


def test_monad_style_config_only_differs_by_env():
    env = {
        "CHAIN_NAME": "monad-testnet",
        "CHAIN_ID": "10143",
        "RPC_URL": "https://testnet-rpc.monad.xyz",
        "USDC_ADDRESS": "0x534b2f3A21130d7a60830c2Df862319e593943A3",
        "EXPLORER_TX_URL": "https://testnet.monadexplorer.com/tx/",
        "GAS_TOKEN_IS_USDC": "false",
    }
    cfg = ChainConfig.from_env(env)
    assert cfg.name == "monad-testnet"
    assert cfg.gas_token_is_usdc is False
    assert cfg.chain_id == 10143


def test_usdc_and_native_decimals_are_different():
    """The trap the plan warns about: same asset, two scales."""
    assert USDC_DECIMALS == 6
    assert NATIVE_DECIMALS == 18
    # One USDC as ERC-20 vs as native balance.
    assert 1 * 10**USDC_DECIMALS == 1_000_000
    assert Decimal(1 * 10**NATIVE_DECIMALS) / Decimal(10**NATIVE_DECIMALS) == Decimal(1)


def _chain():
    from server.chain import ChainClient

    return ChainClient(config=ChainConfig.from_env(ENV), private_key="0x" + "11" * 32)


def test_native_to_usdc_uses_18_decimals():
    chain = _chain()
    assert chain.native_to_usdc(10**18) == Decimal(1)
    assert chain.native_to_usdc(1) == Decimal("0.000000000000000001")
    assert chain.usdc_from_base_units(1_000_000) == Decimal(1)
    # The 1e12 trap: the same integer means wildly different amounts.
    assert chain.usdc_from_base_units(10**18) == Decimal(10**12)
    assert chain.native_to_usdc(10**18) == Decimal(1)


def test_native_and_erc20_agree_to_erc20_precision():
    """Measured on Arc 2026-10-29 for 0x9143…87ec: 223.473480851711701627 native
    vs 223.473480 ERC-20. The ERC-20 balance is the native amount *truncated* to
    6 dp, so compare with ROUND_DOWN, not rounding."""
    chain = _chain()
    native = 223_473_480_851_711_701_627
    erc20_base = 223_473_480
    floored = chain.native_to_usdc(native).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    assert floored == chain.usdc_from_base_units(erc20_base)
    assert chain.native_to_usdc(native) > chain.usdc_from_base_units(erc20_base)
