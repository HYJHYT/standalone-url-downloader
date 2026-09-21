"""封装 yt-dlp 的媒体信息和媒体集合解析能力。"""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from app.models import MediaCollection, MediaItem


def validate_media_url(url: str) -> str:
    """校验并规范化用户输入的媒体页面地址。"""
    normalized_url = url.strip()
    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
        raise ValueError('请输入有效的 http 或 https 地址')
    return normalized_url


def _format_upload_date(value: Any) -> str:
    """将 yt-dlp 返回的日期转换为易读文本。"""
    if not value:
        return '--'
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f'{text[:4]}-{text[4:6]}-{text[6:]}'
    return text


def _build_item(entry: dict[str, Any], fallback_url: str = '') -> MediaItem:
    """将 yt-dlp 的条目字典转换为界面使用的媒体项目。"""
    item_url = str(entry.get('webpage_url') or entry.get('original_url') or entry.get('url') or fallback_url)
    item_id = str(entry.get('id') or item_url)
    return MediaItem(
        id=item_id,
        url=item_url,
        title=str(entry.get('title') or entry.get('id') or '未命名视频'),
        thumbnail=str(entry.get('thumbnail') or ''),
        uploader=str(entry.get('uploader') or entry.get('channel') or ''),
        upload_date=_format_upload_date(entry.get('upload_date')),
        duration=entry.get('duration'),
    )


def _detect_collection_type(info: dict[str, Any]) -> str:
    """根据 yt-dlp 信息判断当前页面的媒体集合类型。"""
    if info.get('_type') == 'playlist' or info.get('entries') is not None:
        extractor = str(info.get('extractor_key') or info.get('extractor') or '').lower()
        if 'search' in extractor or 'search' in str(info.get('webpage_url') or '').lower():
            return '搜索结果'
        if info.get('playlist_type') == 'channel' or info.get('channel'):
            return '用户/频道'
        return '播放列表'
    return '单个视频'


class MediaExtractor:
    """使用 yt-dlp 解析单视频、用户主页、播放列表和搜索结果。"""

    def __init__(self, ffmpeg_location: Path | None = None):
        """保存可选的 FFmpeg 路径并初始化解析器。"""
        self._ffmpeg_location = ffmpeg_location

    def parse(self, url: str) -> MediaCollection:
        """解析 URL 并返回可供界面展示的媒体集合。"""
        normalized_url = validate_media_url(url)
        options = {
            'skip_download': True,
            'extract_flat': 'in_playlist',
            'ignoreerrors': True,
            'quiet': True,
            'no_warnings': True,
        }
        if self._ffmpeg_location:
            options['ffmpeg_location'] = str(self._ffmpeg_location)
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(normalized_url, download=False)
        if not info:
            raise ValueError('没有解析到可用的媒体信息。')

        collection_type = _detect_collection_type(info)
        if '/profile/' in normalized_url.lower():
            collection_type = '用户空间'
        entries = info.get('entries')
        if entries is None:
            items = [_build_item(info, normalized_url)]
        else:
            items = [_build_item(entry) for entry in entries if entry]
        if not items:
            raise ValueError('页面中没有解析到可下载的视频。')
        return MediaCollection(
            source_url=normalized_url,
            title=str(info.get('title') or info.get('playlist_title') or '媒体列表'),
            collection_type=collection_type,
            uploader=str(info.get('uploader') or info.get('channel') or info.get('playlist_uploader') or ''),
            items=items,
        )

    def enrich_item(self, item: MediaItem) -> MediaItem:
        """完整解析单个视频并补全标题、作者、日期、时长和封面信息。"""
        options = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        if self._ffmpeg_location:
            options['ffmpeg_location'] = str(self._ffmpeg_location)
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(item.url, download=False)
        if not info:
            raise ValueError('没有获取到视频详情。')
        enriched_item = _build_item(info, item.url)
        item.id = enriched_item.id
        item.title = enriched_item.title
        item.thumbnail = enriched_item.thumbnail
        item.uploader = enriched_item.uploader
        item.upload_date = enriched_item.upload_date
        item.duration = enriched_item.duration
        item.detail_status = '已完成'
        return item
