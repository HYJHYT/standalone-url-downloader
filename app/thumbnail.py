"""封面图片下载、缓存和缩放工具。"""

from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen


def load_thumbnail_image(url: str, cache_dir: Path, cache_key: str, max_size: tuple[int, int]):
    """下载或读取缓存封面，并返回缩放后的 Pillow 图片对象。"""
    from PIL import Image

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f'{cache_key}.jpg'
    if cache_path.is_file():
        image = Image.open(cache_path)
    else:
        request = Request(url, headers={'User-Agent': 'HY-MediaHub/1.0'})
        with urlopen(request, timeout=20) as response:
            image_data = response.read()
        cache_path.write_bytes(image_data)
        image = Image.open(BytesIO(image_data))
    image = image.convert('RGB')
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    return image


def get_thumbnail_cache_usage(cache_dir: Path) -> tuple[int, int]:
    """统计封面缓存文件数量和总字节数。"""
    if not cache_dir.is_dir():
        return 0, 0
    files = [path for path in cache_dir.iterdir() if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def clear_thumbnail_cache(cache_dir: Path) -> tuple[int, int]:
    """删除封面缓存文件并返回删除数量和释放的字节数。"""
    if not cache_dir.is_dir():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return 0, 0
    deleted_count = 0
    deleted_bytes = 0
    for path in cache_dir.iterdir():
        if not path.is_file():
            continue
        try:
            file_size = path.stat().st_size
            path.unlink()
            deleted_count += 1
            deleted_bytes += file_size
        except OSError:
            continue
    return deleted_count, deleted_bytes
