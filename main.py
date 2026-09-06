"""Wox.Plugin.Random - random number/string/port generator with profiles.

Query usage:
  rand                  list profiles (user-defined + system presets), Enter generates & copies
  rand <name>           filter profiles by name
  rand history [name]   show previously generated values of a profile
  rand reset [name]     clear the no-repeat history of a profile
"""

from __future__ import annotations

import json
import os

from wox_plugin import (
    ChangeQueryParam,
    Context,
    CopyParams,
    CopyType,
    LogLevel,
    Plugin,
    PluginInitParams,
    Query,
    QueryResponse,
    QueryType,
    Result,
    ResultAction,
    ResultTail,
    ResultTailTextCategory,
    ResultTailType,
    WoxImage,
    WoxPreview,
    WoxPreviewType,
)

import generator
from presets import PRESET_PROFILES
from storage import MAX_ENTRIES_PER_KEY, UsedStore

PROFILES_SETTING_KEY = "Profiles"
ENABLE_PRESETS_SETTING_KEY = "EnablePresets"
AUTO_COPY_SETTING_KEY = "AutoCopy"

TYPE_ICONS = {
    "integer": "🔢",
    "decimal": "💯",
    "string": "🔡",
    "uuid": "🆔",
    "port": "🔌",
}

# English fallbacks used when a translation key cannot be resolved. UI strings
# are kept here instead of inline i18n so result rendering never has to guess.
I18N_EN = {
    "preview_prefix": "Peek",
    "rule_no_repeat": "no repeat",
    "rule_can_repeat": "repeats allowed",
    "action_generate_copy": "Generate & copy",
    "action_reset_history": "Reset history",
    "action_view_history": "View history",
    "action_copy": "Copy",
    "notify_generated": "Generated (copied)",
    "notify_history_reset": "History cleared",
    "notify_exhausted_reset": "All possible values were used, history was reset",
    "history_empty": "No history yet",
    "history_used_count": "Generated values",
    "error_prefix": "Invalid rule",
    "preset_port_name": "Available port (deploy)",
    "preset_uuid_name": "UUID v4",
    "preset_code6_name": "6-digit code",
    "preset_password_name": "Strong password (16)",
}


class RandomNumberPlugin(Plugin):
    async def init(self, ctx: Context, params: PluginInitParams) -> None:
        self.api = params.api
        self.plugin_directory = params.plugin_directory
        data_dir = os.path.join(self.plugin_directory, "data")
        self.store = UsedStore(os.path.join(data_dir, "used_values.json"))
        await self.api.log(ctx, LogLevel.INFO, "Random plugin initialized")

    # ------------------------------------------------------------------ i18n

    async def _tr(self, ctx: Context, key: str) -> str:
        try:
            translated = await self.api.get_translation(ctx, key)
        except Exception:
            translated = key
        if not translated or translated == key:
            return I18N_EN.get(key, key)
        return translated

    # -------------------------------------------------------------- settings

    async def _get_setting(self, ctx: Context, key: str, default: str) -> str:
        try:
            value = await self.api.get_setting(ctx, key)
        except Exception:
            return default
        return value if value else default

    # -------------------------------------------------------------- profiles

    async def _user_profiles(self, ctx: Context) -> list[dict]:
        raw = await self._get_setting(ctx, PROFILES_SETTING_KEY, "")
        if not raw:
            return []
        try:
            rows = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict) and str(row.get("Name", "")).strip()]

    async def _all_profiles(self, ctx: Context) -> list[dict]:
        """Normalized profile descriptors: {key, name, name_key, rule, is_preset}."""
        profiles = []
        for row in await self._user_profiles(ctx):
            name = str(row["Name"]).strip()
            profiles.append({"key": f"user:{name}", "name": name, "name_key": "", "rule": row, "is_preset": False})
        enable_presets = await self._get_setting(ctx, ENABLE_PRESETS_SETTING_KEY, "true")
        if enable_presets.lower() != "false":
            for preset in PRESET_PROFILES:
                profiles.append(
                    {
                        "key": preset["key"],
                        "name": "",
                        "name_key": preset["name_key"],
                        "rule": preset["profile"],
                        "is_preset": True,
                    }
                )
        for desc in profiles:
            if desc["is_preset"]:
                desc["name"] = await self._tr(ctx, desc["name_key"])
        return profiles

    async def _resolved_profiles(self, ctx: Context, search: str) -> list[dict]:
        descs = await self._all_profiles(ctx)
        if search:
            lowered = search.lower()
            descs = [d for d in descs if lowered in d["name"].lower()]
        return descs

    # ------------------------------------------------------------- query api

    async def query(self, ctx: Context, query: Query) -> QueryResponse:
        command = (query.command or "").strip().lower()
        if command == "history":
            return await self._query_history(ctx, query)
        if command == "reset":
            return await self._query_reset(ctx, query)
        return await self._query_generate(ctx, query)

    async def _query_generate(self, ctx: Context, query: Query) -> QueryResponse:
        descs = await self._resolved_profiles(ctx, (query.search or "").strip())
        results = [await self._profile_result(ctx, desc) for desc in descs]
        return QueryResponse(results=results)

    async def _profile_result(self, ctx: Context, desc: dict) -> Result:
        name = desc["name"]
        rule = desc["rule"]
        ptype = "integer"
        try:
            ptype = generator.profile_type(rule)
            rule_desc = generator.describe(rule)
            peek = generator.generate(rule, frozenset())
            subtitle = f"{I18N_EN['preview_prefix']}: {peek} | {rule_desc}"
        except Exception as e:
            rule_desc = "-"
            subtitle = f"{I18N_EN['error_prefix']}: {e}"

        no_repeat = generator.is_no_repeat(rule)
        tails = [
            ResultTail(type=ResultTailType.TEXT, text=rule_desc, text_category=ResultTailTextCategory.DEFAULT),
            ResultTail(
                type=ResultTailType.TEXT,
                text=I18N_EN["rule_no_repeat"] if no_repeat else I18N_EN["rule_can_repeat"],
                text_category=ResultTailTextCategory.SUCCESS if no_repeat else ResultTailTextCategory.DEFAULT,
            ),
        ]

        async def on_generate(ctx, action_ctx, desc=desc):
            await self._generate_and_copy(ctx, desc)

        async def on_reset(ctx, action_ctx, desc=desc):
            self.store.clear(desc["key"])
            await self.api.notify(ctx, f"{desc['name']}: {I18N_EN['notify_history_reset']}")

        return Result(
            title=name,
            sub_title=subtitle,
            icon=WoxImage.new_emoji(TYPE_ICONS.get(ptype, "🎲")),
            tails=tails,
            preview=WoxPreview(
                preview_type=WoxPreviewType.MARKDOWN,
                preview_data=self._preview_markdown(name, ptype, rule, desc),
            ),
            actions=[
                ResultAction(name=I18N_EN["action_generate_copy"], is_default=True, action=on_generate),
                ResultAction(name=I18N_EN["action_reset_history"], action=on_reset),
            ],
        )

    def _preview_markdown(self, name: str, ptype: str, rule: dict, desc: dict) -> str:
        try:
            rule_desc = generator.describe(rule)
        except generator.ProfileError:
            rule_desc = "-"
        used = self.store.count(desc["key"])
        no_repeat = "✅" if generator.is_no_repeat(rule) else "❌"
        used_note = f" (history capped at {MAX_ENTRIES_PER_KEY})" if used >= MAX_ENTRIES_PER_KEY else ""
        return "\n".join(
            [
                f"## {name}",
                "",
                f"- **Type**: `{ptype}`",
                f"- **Rule**: `{rule_desc}`",
                f"- **No repeat**: {no_repeat}",
                f"- **Used values**: {used}{used_note}",
            ]
        )

    async def _generate_and_copy(self, ctx: Context, desc: dict) -> None:
        key = desc["key"]
        rule = desc["rule"]
        try:
            try:
                value = generator.generate(rule, self.store.used_values(key))
            except generator.ExhaustedError:
                self.store.clear(key)
                await self.api.notify(ctx, I18N_EN["notify_exhausted_reset"])
                value = generator.generate(rule, frozenset())
            self.store.record(key, value)
        except generator.ProfileError as e:
            await self.api.notify(ctx, f"{I18N_EN['error_prefix']}: {e}")
            return
        except Exception as e:
            await self.api.notify(ctx, f"Error: {e}")
            return
        auto_copy = await self._get_setting(ctx, AUTO_COPY_SETTING_KEY, "true")
        if auto_copy.lower() != "false":
            await self.api.copy(ctx, CopyParams(type=CopyType.TEXT, text=value))
        await self.api.notify(ctx, f"{I18N_EN['notify_generated']}: {value}")

    # -------------------------------------------------------- history command

    async def _query_history(self, ctx: Context, query: Query) -> QueryResponse:
        search = (query.search or "").strip()
        descs = await self._resolved_profiles(ctx, search)
        if not search:
            results = []
            for desc in descs:
                count = self.store.count(desc["key"])

                async def on_view(ctx, action_ctx, desc=desc):
                    await self.api.change_query(
                        ctx,
                        ChangeQueryParam(
                            query_type=QueryType.INPUT,
                            query_text=f"{query.trigger_keyword} history {desc['name']}".strip(),
                        ),
                    )

                results.append(
                    Result(
                        title=desc["name"],
                        sub_title=f"{I18N_EN['history_used_count']}: {count}",
                        icon=WoxImage.new_emoji("🕘"),
                        actions=[
                            ResultAction(name=I18N_EN["action_view_history"], is_default=True, action=on_view)
                        ],
                    )
                )
            return QueryResponse(results=results)

        if not descs:
            return QueryResponse(results=[])
        desc = descs[0]
        entries = self.store.entries(desc["key"])
        if not entries:
            return QueryResponse(
                results=[
                    Result(
                        title=I18N_EN["history_empty"],
                        sub_title=desc["name"],
                        icon=WoxImage.new_emoji("🕘"),
                    )
                ]
            )
        results = []
        for entry in entries[:50]:
            value = entry["v"]

            async def on_copy(ctx, action_ctx, value=value):
                await self.api.copy(ctx, CopyParams(type=CopyType.TEXT, text=value))
                await self.api.notify(ctx, value)

            results.append(
                Result(
                    title=value,
                    sub_title=entry.get("t", ""),
                    icon=WoxImage.new_emoji("🕘"),
                    actions=[ResultAction(name=I18N_EN["action_copy"], is_default=True, action=on_copy)],
                )
            )
        return QueryResponse(results=results)

    # ---------------------------------------------------------- reset command

    async def _query_reset(self, ctx: Context, query: Query) -> QueryResponse:
        search = (query.search or "").strip()
        descs = await self._resolved_profiles(ctx, search)
        results = []
        for desc in descs:
            count = self.store.count(desc["key"])

            async def on_clear(ctx, action_ctx, desc=desc):
                self.store.clear(desc["key"])
                await self.api.notify(ctx, f"{desc['name']}: {I18N_EN['notify_history_reset']}")

            results.append(
                Result(
                    title=desc["name"],
                    sub_title=f"{I18N_EN['history_used_count']}: {count}",
                    icon=WoxImage.new_emoji("🧹"),
                    actions=[
                        ResultAction(name=I18N_EN["action_reset_history"], is_default=True, action=on_clear)
                    ],
                )
            )
        return QueryResponse(results=results)


plugin = RandomNumberPlugin()
