from .SettingsToText import SettingsToText

NODE_CLASS_MAPPINGS = {
    "SettingsToText": SettingsToText
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SettingsToText": "Settings To Text"
}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]