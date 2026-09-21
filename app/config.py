import shutil
import sys
from pathlib import Path

# 应用展示名称，窗口标题和打包程序名称统一使用该名称。
APP_NAME = 'HY MediaHub'
DEFAULT_SOCKET_TIMEOUT = 60
DEFAULT_RETRIES = 10
DEFAULT_FRAGMENT_RETRIES = 10


def resolve_application_dir() -> Path:
    """解析源码模式或打包模式下的应用资源目录。"""
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        return Path(bundle_dir).resolve()
    return Path(__file__).resolve().parents[1]


def resolve_ffmpeg_location() -> Path | None:
    """查找随应用打包的 ffmpeg 目录，源码模式下回退到系统 PATH。"""
    bundled_dir = resolve_application_dir() / 'ffmpeg'
    if (bundled_dir / 'ffmpeg.exe').is_file() and (bundled_dir / 'ffprobe.exe').is_file():
        return bundled_dir

    ffmpeg_path = shutil.which('ffmpeg')
    ffprobe_path = shutil.which('ffprobe')
    if ffmpeg_path and ffprobe_path:
        return Path(ffmpeg_path).resolve().parent
    return None
