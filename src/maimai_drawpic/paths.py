"""插件只读资源位置；运行数据始终使用 SDK 注入的 data_dir。"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parents[1]
ASSET_DIR = PLUGIN_DIR / "assets"
