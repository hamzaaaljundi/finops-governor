"""Hardware profile loading tests (M2, Task 2.2)."""

import pytest

from finops_governor.estimator.profiles import (
    DEFAULT_PROFILE_ID,
    HardwareProfile,
    get_default_profile,
    get_profile,
    load_profiles,
)


def test_profiles_load_and_validate():
    profiles = load_profiles()
    assert profiles, "no profiles loaded"
    assert all(isinstance(p, HardwareProfile) for p in profiles.values())


def test_expected_profiles_present():
    profiles = load_profiles()
    assert {"t4", "a10g", "h100"} <= set(profiles)


def test_default_profile_resolves():
    assert get_default_profile().name == get_profile(DEFAULT_PROFILE_ID).name


def test_all_prices_positive():
    for p in load_profiles().values():
        assert p.price_per_hour_usd > 0


def test_unknown_profile_raises_with_options():
    with pytest.raises(KeyError) as exc:
        get_profile("does-not-exist")
    # error should list the valid ids to help the caller
    assert "a10g" in str(exc.value)
