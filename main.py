"""Wox.Plugin.Random - random number/string/port generator with profiles.

Query usage:
  rand                  list profiles, Enter generates & copies
  rand <name>           filter profiles by name
  rand preset           create a new profile from a preset template
  rand history [name]   show previously generated values of a profile
  rand reset [name]     clear the no-repeat history of a profile
"""

from __future__ import annotations

import json
import os
import sys

# The Wox python host purges only the entry module ("main") from sys.modules
# on reload, so stale copies of our helper modules would survive a reload and
# shadow the freshly synced dist files. Drop them before importing so every
# reload picks up the current code.
for _helper in ("generator", "presets", "storage"):
    sys.modules.pop(_helper, None)

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
    ResultActionType,
    ResultTail,
    ResultTailTextCategory,
    ResultTailType,
    SetSettingOption,
    WoxImage,
    WoxPreview,
    WoxPreviewType,
    create_textbox_setting,
)

import generator
from presets import PRESET_TEMPLATES
from storage import MAX_ENTRIES_PER_KEY, UsedStore

PROFILES_SETTING_KEY = "Profiles"
AUTO_COPY_SETTING_KEY = "AutoCopy"

TYPE_ICONS = {
    "integer": "🔢",
    "decimal": "💯",
    "string": "🔡",
    "uuid": "🆔",
    "port": "🔌",
}

# Empty values for every Profiles table column, so a freshly created row
# shows a complete dialog in the settings UI.
_EMPTY_ROW = {
    "Min": "",
    "Max": "",
    "Decimals": "",
    "Length": "",
    "Charset": "",
    "CustomChars": "",
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
    "action_create_profile": "Create profile",
    "action_toggle_no_repeat": "Toggle no-repeat",
    "action_rename": "Rename",
    "form_new_name_label": "New name",
    "notify_generated": "Generated (copied)",
    "notify_history_reset": "History cleared",
    "notify_exhausted_reset": "All possible values were used, history was reset",
    "notify_profile_created": "Profile created",
    "notify_profile_renamed": "Profile renamed",
    "notify_name_taken": "A profile with this name already exists",
    "notify_name_empty": "Name must not be empty",
    "notify_no_repeat_on": "No-repeat enabled",
    "notify_no_repeat_off": "No-repeat disabled",
    "notify_profile_not_found": "Profile not found",
    "notify_save_failed": "Failed to save settings",
    "history_empty": "No history yet",
    "history_used_count": "Generated values",
    "error_prefix": "Invalid rule",
    "preset_port_name": "Available port (deploy)",
    "preset_uuid_name": "UUID v4",
    "preset_code6_name": "6-digit code",
    "preset_password_name": "Strong password (16)",
    "preset_subtitle": "Preset - select to create a profile from it",
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

    async def _save_setting(self, ctx: Context, key: str, value: str) -> bool:
        try:
            result = await self.api.set_setting(ctx, SetSettingOption(key=key, value=value))
        except Exception:
            return False
        return bool(result and result.success)

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

    async def _resolved_profiles(self, ctx: Context, search: str) -> list[dict]:
        """User profiles as descriptors: {key, name, rule}."""
        descs = []
        for row in await self._user_profiles(ctx):
            name = str(row["Name"]).strip()
            descs.append({"key": f"user:{name}", "name": name, "rule": row})
        if search:
            lowered = search.lower()
            descs = [d for d in descs if lowered in d["name"].lower()]
        return descs

    async def _create_profile(self, ctx: Context, base_name: str, rule: dict) -> str | None:
        """Append a new profile row; returns the (de-duplicated) name or None on failure."""
        rows = await self._user_profiles(ctx)
        taken = {str(row.get("Name", "")).strip() for row in rows}
        name, counter = base_name, 2
        while name in taken:
            name = f"{base_name} {counter}"
            counter += 1
        row = {"Name": name, **_EMPTY_ROW, **rule}
        rows.append(row)
        saved = await self._save_setting(ctx, PROFILES_SETTING_KEY, json.dumps(rows, ensure_ascii=False))
        if not saved:
            await self.api.notify(ctx, I18N_EN["notify_save_failed"])
            return None
        return name

    async def _toggle_no_repeat(self, ctx: Context, name: str) -> bool | None:
        """Flip NoRepeat on the named profile; returns the new state, or None if not found."""
        rows = await self._user_profiles(ctx)
        for row in rows:
            if str(row.get("Name", "")).strip() == name:
                new_state = not generator.is_no_repeat(row)
                row["NoRepeat"] = new_state
                saved = await self._save_setting(ctx, PROFILES_SETTING_KEY, json.dumps(rows, ensure_ascii=False))
                if not saved:
                    await self.api.notify(ctx, I18N_EN["notify_save_failed"])
                    return None
                return new_state
        return None

    async def _rename_profile(self, ctx: Context, old_name: str, new_name: str) -> str:
        """Rename a profile and migrate its history.

        Returns "ok", "empty", "taken", "not_found" or "save_failed".
        """
        new_name = new_name.strip()
        if not new_name:
            return "empty"
        rows = await self._user_profiles(ctx)
        if all(str(row.get("Name", "")).strip() != old_name for row in rows):
            return "not_found"
        if any(str(row.get("Name", "")).strip() == new_name for row in rows):
            return "taken"
        for row in rows:
            if str(row.get("Name", "")).strip() == old_name:
                row["Name"] = new_name
                break
        saved = await self._save_setting(ctx, PROFILES_SETTING_KEY, json.dumps(rows, ensure_ascii=False))
        if not saved:
            return "save_failed"
        self.store.rename(f"user:{old_name}", f"user:{new_name}")
        return "ok"

    # ------------------------------------------------------------- query api

    async def query(self, ctx: Context, query: Query) -> QueryResponse:
        command = (query.command or "").strip().lower()
        if command == "preset":
            return await self._query_preset(ctx, query)
        if command == "history":
            return await self._query_history(ctx, query)
        if command == "reset":
            return await self._query_reset(ctx, query)
        return await self._query_generate(ctx, query)

    async def _query_generate(self, ctx: Context, query: Query) -> QueryResponse:
        descs = await self._resolved_profiles(ctx, (query.search or "").strip())
        results = [await self._profile_result(ctx, desc, query.trigger_keyword) for desc in descs]
        return QueryResponse(results=results)

    async def _profile_result(self, ctx: Context, desc: dict, trigger_keyword: str = "") -> Result:
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

        async def on_rename_submit(ctx, form_ctx, name=name):
            status = await self._rename_profile(ctx, name, form_ctx.values.get("new_name", ""))
            if status == "ok":
                await self.api.notify(ctx, f"{I18N_EN['notify_profile_renamed']}: {name} -> {form_ctx.values.get('new_name', '').strip()}")
                # the old search term may no longer match; go back to the full list
                await self.api.change_query(
                    ctx,
                    ChangeQueryParam(query_type=QueryType.INPUT, query_text=(trigger_keyword or "").strip()),
                )
            elif status == "empty":
                await self.api.notify(ctx, I18N_EN["notify_name_empty"])
            elif status == "taken":
                await self.api.notify(ctx, I18N_EN["notify_name_taken"])
            elif status == "save_failed":
                await self.api.notify(ctx, I18N_EN["notify_save_failed"])
            else:
                await self.api.notify(ctx, I18N_EN["notify_profile_not_found"])

        async def on_toggle(ctx, action_ctx, name=name):
            new_state = await self._toggle_no_repeat(ctx, name)
            if new_state is True:
                await self.api.notify(ctx, f"{name}: {I18N_EN['notify_no_repeat_on']}")
            elif new_state is False:
                await self.api.notify(ctx, f"{name}: {I18N_EN['notify_no_repeat_off']}")
            else:
                await self.api.notify(ctx, f"{name}: {I18N_EN['notify_profile_not_found']}")

        async def on_reset(ctx, action_ctx, name=name):
            self.store.clear(f"user:{name}")
            await self.api.notify(ctx, f"{name}: {I18N_EN['notify_history_reset']}")

        return Result(
            title=name,
            sub_title=subtitle,
            icon=WoxImage.new_emoji(TYPE_ICONS.get(ptype, "🎲")),
            tails=tails,
            preview=WoxPreview(
                preview_type=WoxPreviewType.MARKDOWN,
                preview_data=self._preview_markdown(name, ptype, rule, desc["key"]),
            ),
            actions=[
                ResultAction(name=I18N_EN["action_generate_copy"], is_default=True, action=on_generate),
                ResultAction(
                    name=I18N_EN["action_rename"],
                    type=ResultActionType.FORM,
                    form=[create_textbox_setting("new_name", I18N_EN["form_new_name_label"], default_value=name)],
                    on_submit=on_rename_submit,
                    prevent_hide_after_action=True,
                ),
                ResultAction(name=I18N_EN["action_toggle_no_repeat"], action=on_toggle),
                ResultAction(name=I18N_EN["action_reset_history"], action=on_reset),
            ],
        )

    def _preview_markdown(self, name: str, ptype: str, rule: dict, history_key: str) -> str:
        try:
            rule_desc = generator.describe(rule)
        except generator.ProfileError:
            rule_desc = "-"
        used = self.store.count(history_key)
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

    # --------------------------------------------------------- preset command

    async def _query_preset(self, ctx: Context, query: Query) -> QueryResponse:
        search = (query.search or "").strip().lower()
        results = []
        for template in PRESET_TEMPLATES:
            name = await self._tr(ctx, template["name_key"])
            if search and search not in name.lower():
                continue
            rule = template["row"]

            async def on_create(ctx, action_ctx, template=template, trigger=query.trigger_keyword):
                created = await self._create_profile(ctx, await self._tr(ctx, template["name_key"]), template["row"])
                if created is not None:
                    await self.api.notify(ctx, f"{I18N_EN['notify_profile_created']}: {created}")
                    await self.api.change_query(
                        ctx,
                        ChangeQueryParam(query_type=QueryType.INPUT, query_text=(trigger or "").strip()),
                    )

            try:
                subtitle = f"{I18N_EN['preset_subtitle']} | {generator.describe(rule)}"
            except generator.ProfileError:
                subtitle = I18N_EN["preset_subtitle"]

            results.append(
                Result(
                    title=name,
                    sub_title=subtitle,
                    icon=WoxImage.new_emoji("📦"),
                    actions=[ResultAction(name=I18N_EN["action_create_profile"], is_default=True, action=on_create)],
                )
            )
        return QueryResponse(results=results)

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
