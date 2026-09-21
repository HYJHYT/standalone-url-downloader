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
    detail_status: str = '待解析'
    selected: bool = False

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
class DownloadOptions:
    """描述单个下载任务使用的视频、音频和附加资源选项。"""

    quality: str = 'best'
    mode: str = 'video_audio'
    write_thumbnail: bool = False
    write_subtitles: bool = False
    embed_thumbnail: bool = False
    embed_subs: bool = False
    subtitles_lang: str = 'zh-Hans,zh,en'
    audio_format: str = 'm4a'
    output_template: str = '%(title).180B [%(id)s].%(ext)s'


@dataclass(slots=True)
class DownloadTask:
    """表示队列中的一个下载任务。"""

    item: MediaItem
    options: DownloadOptions = field(default_factory=DownloadOptions)
    status: str = '等待中'
    error: str = ''
