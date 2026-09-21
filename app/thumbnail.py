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
