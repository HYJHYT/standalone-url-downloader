"""HY MediaHub 使用的媒体和下载任务数据模型。"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class MediaItem:
    """表示列表中的一个可下载媒体项目。"""

    id: str
    url: str
    title: str
    thumbnail: str = ''
    uploader: str = ''
    upload_date: str = ''
    duration: int | None = None
    status: str = '等待中'

    def duration_text(self) -> str:
        """将秒数转换为适合列表显示的时长文本。"""
        if self.duration is None:
            return '--'
        seconds = max(0, int(self.duration))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'


@dataclass(slots=True)
class MediaCollection:
    """表示一个单视频或一组视频的解析结果。"""

    source_url: str
    title: str
    collection_type: str
    uploader: str = ''
    items: list[MediaItem] = field(default_factory=list)


@dataclass(slots=True)
class DownloadTask:
    """表示队列中的一个下载任务。"""

    item: MediaItem
    status: str = '等待中'
    error: str = ''
