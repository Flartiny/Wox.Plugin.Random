"""Preset templates for creating user profiles.

Presets are NOT runnable profiles themselves: each one is instantiated into a
normal user profile (stored in the Profiles table setting) via the
``rand preset`` command, so several profiles can be created from the same
preset with independent no-repeat histories (e.g. one per server).
"""

from __future__ import annotations

# Each template: stable "key", a name translation key, and the rule columns
# for the Profiles table row (same keys as the setting columns).
PRESET_TEMPLATES = [
    {
        "key": "port",
        "name_key": "preset_port_name",
        "row": {"Type": "port", "Min": "1024", "Max": "65535", "NoRepeat": True},
    },
    {
        "key": "uuid",
        "name_key": "preset_uuid_name",
        "row": {"Type": "uuid", "NoRepeat": True},
    },
    {
        "key": "code6",
        "name_key": "preset_code6_name",
        "row": {"Type": "string", "Length": "6", "Charset": "digits", "NoRepeat": False},
    },
    {
        "key": "password",
        "name_key": "preset_password_name",
        "row": {"Type": "string", "Length": "16", "Charset": "alphanumeric", "NoRepeat": False},
    },
]
