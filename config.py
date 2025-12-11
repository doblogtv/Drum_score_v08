import json
import logging
import os

APP_VERSION = "0.7"

CONFIG_FILE = os.path.join(os.getcwd(), "drum_app_config.json")

# NOTE: gui_app.py など UI 層と共有する設定キー
SHARED_CONFIG_KEYS = {
    "save_dir",
    "movie_output_dir",
    "loop_record_count",
    "loop_playback",
    "sound_settings",
    "sample_paths",
    "last_file",
    "main_geometry",
    "text_geometry",
}

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """設定ファイルの読み込み（なければ空dict）"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.exception("Failed to load config from %s", CONFIG_FILE)
        print(f"[ERROR] Failed to load config: {exc}")
        return {}


def save_config(config: dict):
    """設定ファイルの保存"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.exception("Failed to save config to %s", CONFIG_FILE)
        print(f"[ERROR] Failed to save config: {exc}")
