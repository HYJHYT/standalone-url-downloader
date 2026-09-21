"""HY MediaHub 的 SQLite 下载历史和重复检测服务。"""

import sqlite3
from datetime import datetime
from pathlib import Path

from app.models import MediaItem


class DownloadHistory:
    """保存成功下载记录，并根据文件是否仍存在判断是否可以跳过。"""

    def __init__(self, database_path: Path):
        """初始化数据库目录并创建历史记录表。"""
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """创建一个启用行名称访问的 SQLite 连接。"""
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """创建下载历史表和视频 ID 索引。"""
        with self._connect() as connection:
            connection.execute(
                '''CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    downloaded_at TEXT NOT NULL
                )'''
            )

    def find_existing(self, item: MediaItem) -> Path | None:
        """查找仍存在于磁盘上的成功下载文件。"""
        with self._connect() as connection:
            record = connection.execute(
                'SELECT file_path FROM downloads WHERE id = ?', (item.id,)
            ).fetchone()
        if not record:
            return None
        file_path = Path(record['file_path'])
        return file_path if file_path.is_file() else None

    def record_success(self, item: MediaItem, file_path: Path) -> None:
        """写入或更新一条成功下载记录。"""
        with self._connect() as connection:
            connection.execute(
                '''INSERT INTO downloads (id, url, title, file_path, downloaded_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                   url=excluded.url, title=excluded.title,
                   file_path=excluded.file_path, downloaded_at=excluded.downloaded_at''',
                (item.id, item.url, item.title, str(file_path), datetime.now().isoformat(timespec='seconds')),
            )
