"""System preset profiles built into the plugin."""

from __future__ import annotations

# Each preset: stable "key" (used as the no-repeat history key), a name
# translation key, and a profile rule dict with the same columns as the
# user-defined Profiles table setting.
PRESET_PROFILES = [
    {
        "key": "preset:port",
        "name_key": "preset_port_name",
        "profile": {"Type": "port", "Min": "1024", "Max": "65535", "NoRepeat": True},
    },
    {
        "key": "preset:uuid",
        "name_key": "preset_uuid_name",
        "profile": {"Type": "uuid", "NoRepeat": True},
    },
    {
        "key": "preset:code6",
        "name_key": "preset_code6_name",
        "profile": {"Type": "string", "Length": "6", "Charset": "digits", "NoRepeat": False},
    },
    {
        "key": "preset:password",
        "name_key": "preset_password_name",
        "profile": {"Type": "string", "Length": "16", "Charset": "alphanumeric", "NoRepeat": False},
    },
]
