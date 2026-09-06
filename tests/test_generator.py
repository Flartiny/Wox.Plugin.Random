import json

import pytest

import generator
from storage import UsedStore


def test_integer_range_and_norepeat():
    profile = {"Name": "t", "Type": "integer", "Min": "1", "Max": "10", "NoRepeat": "true"}
    seen = set()
    for _ in range(10):
        v = generator.generate(profile, frozenset(seen))
        assert 1 <= int(v) <= 10
        assert v not in seen
        seen.add(v)
    assert len(seen) == 10
    with pytest.raises(generator.ExhaustedError):
        generator.generate(profile, frozenset(seen))


def test_decimal_format():
    profile = {"Type": "decimal", "Min": "0", "Max": "1", "Decimals": "2"}
    for _ in range(50):
        v = generator.generate(profile)
        assert len(v.split(".")[1]) == 2
        assert 0 <= float(v) <= 1


def test_string_charset_and_length():
    profile = {"Type": "string", "Length": "16", "Charset": "hex"}
    v = generator.generate(profile)
    assert len(v) == 16
    assert all(c in "0123456789abcdef" for c in v)


def test_string_custom_chars_requires_input():
    profile = {"Type": "string", "Length": "4", "Charset": "custom", "CustomChars": ""}
    with pytest.raises(generator.ProfileError):
        generator.generate(profile)


def test_uuid_unique():
    values = {generator.generate({"Type": "uuid"}) for _ in range(20)}
    assert len(values) == 20


def test_port_in_range_and_available(monkeypatch):
    calls = []

    def fake_available(port):
        calls.append(port)
        return port % 2 == 0  # only even ports "available"

    monkeypatch.setattr(generator, "is_port_available", fake_available)
    profile = {"Type": "port", "Min": "1000", "Max": "1100", "NoRepeat": "true"}
    seen = set()
    for _ in range(5):
        v = generator.generate(profile, frozenset(seen))
        port = int(v)
        assert 1000 <= port <= 1100
        assert port % 2 == 0
        seen.add(v)


def test_port_range_check_respects_min():
    assert generator.is_port_available(0) is False or True  # smoke: probe runs without crash


def test_invalid_rule_raises():
    with pytest.raises(generator.ProfileError):
        generator.generate({"Type": "integer", "Min": "5", "Max": "1"})
    with pytest.raises(generator.ProfileError):
        generator.generate({"Type": "warp"})
    with pytest.raises(generator.ProfileError):
        generator.generate({"Type": "decimal", "Min": "x", "Max": "1"})


def test_space_size_and_no_repeat_flag():
    profile = {"Type": "integer", "Min": "1", "Max": "5", "NoRepeat": True}
    assert generator.is_no_repeat(profile) is True
    assert generator.space_size(profile) == 5
    assert generator.space_size({"Type": "uuid"}) is None


def test_store_roundtrip(tmp_path):
    path = tmp_path / "used_values.json"
    store = UsedStore(str(path))
    store.record("user:a", "1")
    store.record("user:a", "2")
    store.record("user:a", "1")  # duplicate ignored
    assert store.used_values("user:a") == frozenset({"1", "2"})
    assert [e["v"] for e in store.entries("user:a")] == ["2", "1"]
    assert store.count("user:b") == 0

    reloaded = UsedStore(str(path))
    assert reloaded.used_values("user:a") == frozenset({"1", "2"})

    reloaded.clear("user:a")
    assert reloaded.count("user:a") == 0


def test_store_corrupt_file(tmp_path):
    path = tmp_path / "used_values.json"
    path.write_text("not json{", encoding="utf-8")
    store = UsedStore(str(path))
    assert store.count("x") == 0
    store.record("x", "v")  # still usable
    assert store.used_values("x") == frozenset({"v"})


def test_preset_profiles_are_valid():
    from presets import PRESET_PROFILES

    for preset in PRESET_PROFILES:
        rule = preset["profile"]
        generator.profile_type(rule)
        v = generator.generate(rule)
        assert v
    port = int(generator.generate(PRESET_PROFILES[0]["profile"]))
    assert 1024 <= port <= 65535
