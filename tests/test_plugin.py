"""Smoke test for the plugin class with a fake Wox API (no live Wox needed)."""

import asyncio
import json
import os
import tempfile

import main
from storage import UsedStore


class FakeAPI:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.notifications = []
        self.copied = []
        self.queries = []
        self.plugin_directory = "."

    async def get_setting(self, ctx, key):
        return self.settings.get(key, "")

    async def set_setting(self, ctx, option):
        self.settings[option.key] = option.value
        return type("R", (), {"success": True, "errmsg": ""})()

    async def get_translation(self, ctx, key):
        return key  # unresolved -> falls back to English dict

    async def notify(self, ctx, message):
        self.notifications.append(message)

    async def copy(self, ctx, params):
        self.copied.append(params.text)

    async def change_query(self, ctx, param):
        self.queries.append(param.query_text)

    async def refresh_query(self, ctx, param):
        self.refreshed = True

    async def log(self, ctx, level, msg):
        pass


class FakeQuery:
    def __init__(self, command="", search="", trigger_keyword="rand"):
        self.command = command
        self.search = search
        self.trigger_keyword = trigger_keyword


class FakeCtx:
    pass


def make_plugin(settings=None):
    plugin = main.RandomNumberPlugin()
    plugin.api = FakeAPI(settings)
    plugin.plugin_directory = tempfile.mkdtemp()
    plugin.store = UsedStore(os.path.join(plugin.plugin_directory, "data", "used_values.json"))
    return plugin


def run(coro):
    return asyncio.run(coro)


def test_generate_query_lists_only_user_profiles():
    plugin = make_plugin({
        "Profiles": json.dumps([
            {"Name": "幸运数字", "Type": "integer", "Min": "1", "Max": "100", "NoRepeat": False},
            {"Name": "订单号", "Type": "string", "Length": "8", "Charset": "digits", "NoRepeat": True},
        ])
    })
    response = run(plugin.query(FakeCtx(), FakeQuery()))
    assert [r.title for r in response.results] == ["幸运数字", "订单号"]
    assert all("Peek:" in r.sub_title or "Invalid rule" in r.sub_title for r in response.results)
    assert all(len(r.actions) == 4 for r in response.results)  # generate / rename / toggle / reset


def test_search_filters_profiles():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "订单号", "Type": "uuid"}]),
    })
    response = run(plugin.query(FakeCtx(), FakeQuery(search="订单")))
    assert [r.title for r in response.results] == ["订单号"]
    response = run(plugin.query(FakeCtx(), FakeQuery(search="nope")))
    assert response.results == []


def test_generate_action_records_and_copies():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "端口", "Type": "port", "NoRepeat": True}]),
        "AutoCopy": "true",
    })
    result = run(plugin.query(FakeCtx(), FakeQuery(search="端口"))).results[0]
    run(result.actions[0].action(None, None))
    assert len(plugin.store.used_values("user:端口")) == 1
    assert len(plugin.api.copied) == 1
    assert "Generated (copied)" in plugin.api.notifications[0]
    port = int(plugin.api.copied[0])
    assert 1024 <= port <= 65535

    # second generation must not repeat
    run(result.actions[0].action(None, None))
    assert len(plugin.store.used_values("user:端口")) == 2


def test_exhausted_history_resets():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "小", "Type": "integer", "Min": "1", "Max": "2", "NoRepeat": True}]),
    })
    result = run(plugin.query(FakeCtx(), FakeQuery(search="小"))).results[0]
    run(result.actions[0].action(None, None))
    run(result.actions[0].action(None, None))
    # history now holds both values; next call exhausts the space, auto-resets
    run(result.actions[0].action(None, None))
    assert plugin.store.count("user:小") == 1
    assert any("history was reset" in n for n in plugin.api.notifications)


def test_toggle_no_repeat_action():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "小", "Type": "integer", "Min": "1", "Max": "100", "NoRepeat": False}]),
    })
    result = run(plugin.query(FakeCtx(), FakeQuery(search="小"))).results[0]
    toggle = result.actions[2]
    run(toggle.action(None, None))
    rows = json.loads(plugin.api.settings["Profiles"])
    assert rows[0]["NoRepeat"] is True
    assert any("No-repeat enabled" in n for n in plugin.api.notifications)
    run(toggle.action(None, None))
    rows = json.loads(plugin.api.settings["Profiles"])
    assert rows[0]["NoRepeat"] is False


def test_preset_command_lists_templates():
    plugin = make_plugin()
    response = run(plugin.query(FakeCtx(), FakeQuery(command="preset")))
    assert [r.title for r in response.results] == [
        "Available port (deploy)", "UUID v4", "6-digit code", "Strong password (16)"
    ]


def test_preset_search_filters():
    plugin = make_plugin()
    response = run(plugin.query(FakeCtx(), FakeQuery(command="preset", search="uuid")))
    assert [r.title for r in response.results] == ["UUID v4"]


def test_preset_create_profile():
    plugin = make_plugin()
    response = run(plugin.query(FakeCtx(), FakeQuery(command="preset")))
    run(response.results[0].actions[0].action(None, None))  # create the port profile
    rows = json.loads(plugin.api.settings["Profiles"])
    assert len(rows) == 1
    assert rows[0]["Name"] == "Available port (deploy)"
    assert rows[0]["Type"] == "port"
    assert rows[0]["NoRepeat"] is True
    assert any("Profile created" in n for n in plugin.api.notifications)
    assert plugin.api.queries == ["rand"]  # switches back to the profile list


def test_preset_create_dedupes_names():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "Available port (deploy)", "Type": "port", "NoRepeat": True}]),
    })
    response = run(plugin.query(FakeCtx(), FakeQuery(command="preset")))
    run(response.results[0].actions[0].action(None, None))
    rows = json.loads(plugin.api.settings["Profiles"])
    assert [r["Name"] for r in rows] == ["Available port (deploy)", "Available port (deploy) 2"]


def test_reset_action_clears_history():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "小", "Type": "integer", "Min": "1", "Max": "100", "NoRepeat": True}]),
    })
    plugin.store.record("user:小", "42")
    result = run(plugin.query(FakeCtx(), FakeQuery(command="reset", search="小"))).results[0]
    run(result.actions[0].action(None, None))
    assert plugin.store.count("user:小") == 0


def test_history_flow():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "小", "Type": "integer", "Min": "1", "Max": "100"}]),
    })
    plugin.store.record("user:小", "42")
    plugin.store.record("user:小", "43")

    # empty search -> profile list
    response = run(plugin.query(FakeCtx(), FakeQuery(command="history")))
    assert [r.title for r in response.results] == ["小"]

    # search -> values, newest first
    response = run(plugin.query(FakeCtx(), FakeQuery(command="history", search="小")))
    assert [r.title for r in response.results] == ["43", "42"]
    run(response.results[0].actions[0].action(None, None))
    assert plugin.api.copied == ["43"]


def test_invalid_profile_shows_error_not_crash():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "坏规则", "Type": "integer", "Min": "10", "Max": "1"}]),
    })
    response = run(plugin.query(FakeCtx(), FakeQuery(search="坏规则")))
    assert "Invalid rule" in response.results[0].sub_title
    run(response.results[0].actions[0].action(None, None))
    assert any("Invalid rule" in n for n in plugin.api.notifications)


def test_reload_purges_stale_helper_modules():
    """Reproduces the Wox host reload bug: helper modules stay cached in
    sys.modules across reloads; main.py must drop them before importing."""
    import importlib
    import sys
    import types

    stale = types.ModuleType("presets")  # old version without PRESET_TEMPLATES
    sys.modules["presets"] = stale
    try:
        importlib.reload(main)  # must not raise ImportError
        import presets

        assert hasattr(presets, "PRESET_TEMPLATES")
    finally:
        importlib.reload(main)  # restore a clean import state for other tests


class FakeFormCtx:
    def __init__(self, values):
        self.values = values


def test_rename_profile_migrates_history():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "旧名", "Type": "integer", "Min": "1", "Max": "100", "NoRepeat": True}]),
    })
    plugin.store.record("user:旧名", "42")
    result = run(plugin.query(FakeCtx(), FakeQuery(search="旧名"))).results[0]
    rename = result.actions[1]
    assert rename.type == "form"

    run(rename.on_submit(FakeCtx(), FakeFormCtx({"new_name": "  新名 "})))
    rows = json.loads(plugin.api.settings["Profiles"])
    assert rows[0]["Name"] == "新名"
    # history migrated to the new name
    assert plugin.store.used_values("user:新名") == frozenset({"42"})
    assert plugin.store.count("user:旧名") == 0
    assert any("renamed" in n for n in plugin.api.notifications)
    assert plugin.api.queries == ["rand"]  # back to the full profile list


def test_rename_rejects_duplicate_and_empty():
    plugin = make_plugin({
        "Profiles": json.dumps([
            {"Name": "A", "Type": "integer", "Min": "1", "Max": "2"},
            {"Name": "B", "Type": "integer", "Min": "1", "Max": "2"},
        ]),
    })
    plugin.store.record("user:A", "1")
    result = run(plugin.query(FakeCtx(), FakeQuery(search="A"))).results[0]
    rename = result.actions[1]

    run(rename.on_submit(FakeCtx(), FakeFormCtx({"new_name": "B"})))
    assert any("already exists" in n for n in plugin.api.notifications)
    assert [r["Name"] for r in json.loads(plugin.api.settings["Profiles"])] == ["A", "B"]
    assert plugin.store.used_values("user:A") == frozenset({"1"})

    run(rename.on_submit(FakeCtx(), FakeFormCtx({"new_name": "   "})))
    assert any("must not be empty" in n for n in plugin.api.notifications)
    assert [r["Name"] for r in json.loads(plugin.api.settings["Profiles"])] == ["A", "B"]
