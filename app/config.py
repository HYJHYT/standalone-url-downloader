import os
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


def resolve_data_dir() -> Path:
    """解析用户数据目录，避免把数据库写入打包程序目录。"""
    # APPDATA 是 Windows 用户级应用数据目录，用于保存下载历史等可写数据。
    app_data = os.environ.get('APPDATA')
    if app_data:
        return Path(app_data) / 'HY MediaHub'
    return Path.home() / '.hy-mediahub'


def resolve_history_database() -> Path:
    """返回下载历史 SQLite 数据库路径。"""
    return resolve_data_dir() / 'history.sqlite3'


def resolve_thumbnail_cache_dir() -> Path:
    """返回封面图片缓存目录。"""
    return resolve_data_dir() / 'thumbnails'
