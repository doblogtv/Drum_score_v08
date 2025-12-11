import os
import json

APP_VERSION = "0.7"

CONFIG_FILE = os.path.join(os.getcwd(), "drum_app_config.json")


def load_config() -> dict:
    """設定ファイルの読み込み（なければ空dict）"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict):
    """設定ファイルの保存"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
