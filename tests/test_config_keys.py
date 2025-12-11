import importlib
import sys
import types
import unittest

import config


def _install_test_stubs():
    """必要モジュールが無い環境でも gui_app をインポートできるようにする。"""

    class _AttrStub(types.SimpleNamespace):
        def __getattr__(self, name):
            return self

        def __call__(self, *args, **kwargs):
            return self

    stub = _AttrStub()
    sys.modules.setdefault("numpy", stub)
    sys.modules.setdefault("simpleaudio", stub)
    sys.modules.setdefault("winsound", stub)


class ConfigKeySyncTest(unittest.TestCase):
    """共有設定キーのずれを検知する簡易チェック。"""

    @classmethod
    def setUpClass(cls):
        _install_test_stubs()
        cls.gui_app = importlib.import_module("gui_app")

    def test_shared_config_keys_are_synced(self):
        self.assertSetEqual(self.gui_app.CONFIG_KEYS, config.SHARED_CONFIG_KEYS)


if __name__ == "__main__":
    unittest.main()
