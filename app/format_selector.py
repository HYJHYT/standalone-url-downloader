"""将界面中的下载选项转换为 yt-dlp 参数。"""

from app.models import DownloadOptions


def build_format_selector(options: DownloadOptions) -> str:
    """根据画质和视频模式生成 yt-dlp 格式选择表达式。"""
    if options.mode == 'audio':
        return 'ba/b'
    if options.mode == 'video':
        base = 'bv'
    else:
        base = 'bv*'
    if options.quality == 'best':
        return f'{base}+ba/b' if options.mode == 'video_audio' else base
    if options.quality == 'audio_best':
        return 'ba/b'
    try:
        height = int(options.quality)
    except ValueError:
        return f'{base}+ba/b' if options.mode == 'video_audio' else base
    video_format = f'{base}[height<={height}]'
    return f'{video_format}+ba/b' if options.mode == 'video_audio' else video_format
