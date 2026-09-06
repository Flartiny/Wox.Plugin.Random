"""Smoke test for the plugin class with a fake Wox API (no live Wox needed)."""

import asyncio
import json
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

    async def get_translation(self, ctx, key):
        return key  # unresolved -> falls back to English dict

    async def notify(self, ctx, message):
        self.notifications.append(message)

    async def copy(self, ctx, params):
        self.copied.append(params.text)

    async def change_query(self, ctx, param):
        self.queries.append(param.query_text)

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
    plugin.store = UsedStore(
        __import__("os").path.join(plugin.plugin_directory, "data", "used_values.json")
    )
    return plugin


def run(coro):
    return asyncio.run(coro)


def test_generate_query_lists_profiles():
    plugin = make_plugin({
        "Profiles": json.dumps([
            {"Name": "幸运数字", "Type": "integer", "Min": "1", "Max": "100", "NoRepeat": False},
            {"Name": "订单号", "Type": "string", "Length": "8", "Charset": "digits", "NoRepeat": True},
        ])
    })
    response = run(plugin.query(FakeCtx(), FakeQuery()))
    names = [r.title for r in response.results]
    assert names == ["幸运数字", "订单号", "Available port (deploy)", "UUID v4", "6-digit code", "Strong password (16)"]
    assert all("Peek:" in r.sub_title or "Invalid rule" in r.sub_title for r in response.results)
    assert all(r.actions for r in response.results)


def test_search_filters_profiles():
    plugin = make_plugin({
        "Profiles": json.dumps([{"Name": "订单号", "Type": "uuid"}]),
    })
    response = run(plugin.query(FakeCtx(), FakeQuery(search="订单")))
    assert [r.title for r in response.results] == ["订单号"]
    response = run(plugin.query(FakeCtx(), FakeQuery(search="uuid")))
    assert [r.title for r in response.results] == ["UUID v4"]
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
    assert [r.title for r in response.results] == ["小", "Available port (deploy)", "UUID v4", "6-digit code", "Strong password (16)"]

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


def test_presets_can_be_disabled():
    plugin = make_plugin({"EnablePresets": "false"})
    response = run(plugin.query(FakeCtx(), FakeQuery()))
    assert response.results == []
