import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from app.config import (
    DEFAULT_FRAGMENT_RETRIES,
    DEFAULT_RETRIES,
    DEFAULT_SOCKET_TIMEOUT,
    resolve_ffmpeg_location,
)


class UserCancelledError(Exception):
    """表示用户主动取消下载。"""


@dataclass(slots=True)
class DownloadProgress:
    """描述一次下载进度更新。"""

    status: str
    title: str
    percentage: float
    downloaded_bytes: int
    total_bytes: int
    speed_text: str
    eta_text: str


ProgressCallback = Callable[[DownloadProgress], None]


def validate_video_url(url: str) -> str:
    """校验视频 URL，仅允许包含主机名的 HTTP 或 HTTPS 地址。"""
    normalized_url = url.strip()
    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
        raise ValueError('请输入有效的 http 或 https 视频地址')
    return normalized_url


def _format_bytes(value: float | int | None) -> str:
    """将字节数格式化为便于阅读的文本。"""
    if value is None:
        return '--'
    size = float(value)
    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f'{size:.1f} {units[unit_index]}'


def _format_speed(value: float | int | None) -> str:
    """将每秒下载字节数格式化为速度文本。"""
    if not value:
        return '--'
    return f'{_format_bytes(value)}/s'


def _format_eta(value: float | int | None) -> str:
    """将剩余秒数格式化为时分秒文本。"""
    if value is None:
        return '--'
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
    return f'{minutes:02d}:{seconds:02d}'


def build_friendly_error(error: Exception) -> str:
    """将 yt-dlp 原始异常转换为更容易理解的中文提示。"""
    raw_message = str(error).strip()
    lowered_message = raw_message.casefold()
    if 'timed out' in lowered_message or 'timeout' in lowered_message:
        return '连接视频服务器超时。程序已经自动重试，请稍后再试或更换网络/代理节点。'
    if 'geo-restricted' in lowered_message:
        return '该视频存在地区限制，当前网络无法访问。'
    if 'private video' in lowered_message or 'login required' in lowered_message:
        return '该视频需要登录或没有公开访问权限。'
    if 'unsupported url' in lowered_message:
        return '当前版本的 yt-dlp 暂不支持这个视频地址。'
    if 'ffmpeg' in lowered_message:
        return '内置 ffmpeg 执行失败，请重新下载或重新构建程序。'
    return raw_message or '下载失败，请检查视频地址和网络连接。'


class VideoDownloader:
    """封装单个公开视频的下载、重试、进度和取消逻辑。"""

    def __init__(self, progress_callback: ProgressCallback):
        """保存进度回调并初始化取消事件。"""
        self._progress_callback = progress_callback
        self._cancel_event = threading.Event()
        self._title = '正在解析视频信息'

    def cancel(self) -> None:
        """请求取消当前下载任务。"""
        self._cancel_event.set()

    def _raise_if_cancelled(self) -> None:
        """在收到取消请求时终止 yt-dlp 下载流程。"""
        if self._cancel_event.is_set():
            raise DownloadCancelled()

    def _emit_progress(self, data: dict) -> None:
        """将 yt-dlp 进度字典转换为界面使用的进度对象。"""
        self._raise_if_cancelled()
        status = str(data.get('status') or '')
        if status not in {'downloading', 'finished'}:
            return
        info = data.get('info_dict') or {}
        self._title = str(info.get('title') or self._title)
        total_bytes = int(data.get('total_bytes') or data.get('total_bytes_estimate') or 0)
        downloaded_bytes = int(data.get('downloaded_bytes') or 0)
        percentage = min(100.0, downloaded_bytes * 100 / total_bytes) if total_bytes else 0.0
        progress_status = 'processing' if status == 'finished' else 'downloading'
        self._progress_callback(DownloadProgress(
            status=progress_status,
            title=self._title,
            percentage=percentage,
            downloaded_bytes=downloaded_bytes,
            total_bytes=total_bytes,
            speed_text=_format_speed(data.get('speed')),
            eta_text=_format_eta(data.get('eta')),
        ))

    def _build_options(self, output_dir: Path) -> dict:
        """构建适合桌面工具的 yt-dlp 下载参数。"""
        ffmpeg_location = resolve_ffmpeg_location()
        if ffmpeg_location is None:
            raise RuntimeError('未找到 ffmpeg 和 ffprobe，请重新构建程序或将它们加入 PATH')
        return {
            'format': 'bv*+ba/b',
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'outtmpl': str(output_dir / '%(title).180B [%(id)s].%(ext)s'),
            'windowsfilenames': True,
            'progress_hooks': [self._emit_progress],
            'ffmpeg_location': str(ffmpeg_location),
            'socket_timeout': DEFAULT_SOCKET_TIMEOUT,
            'retries': DEFAULT_RETRIES,
            'fragment_retries': DEFAULT_FRAGMENT_RETRIES,
            'extractor_retries': 3,
            'file_access_retries': 5,
            'continuedl': True,
            'concurrent_fragment_downloads': 1,
            'quiet': True,
            'no_warnings': True,
        }

    def download(self, url: str, output_dir: str | Path) -> str:
        """下载单个视频到指定目录并返回视频标题。"""
        normalized_url = validate_video_url(url)
        resolved_output_dir = Path(output_dir).expanduser().resolve()
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
        self._cancel_event.clear()
        try:
            with yt_dlp.YoutubeDL(self._build_options(resolved_output_dir)) as downloader:
                info = downloader.extract_info(normalized_url, download=True)
                self._raise_if_cancelled()
                self._title = str(info.get('title') or self._title)
                return self._title
        except DownloadCancelled as exc:
            raise UserCancelledError('下载已取消') from exc

