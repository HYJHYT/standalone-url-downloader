"""批量下载任务队列。"""

import threading
from collections.abc import Callable

from app.downloader import UserCancelledError, VideoDownloader, build_friendly_error
from app.history import DownloadHistory
from app.models import DownloadTask


class DownloadQueue:
    """按顺序执行多个视频下载任务并提供状态回调。"""

    def __init__(
        self,
        on_started: Callable[[DownloadTask], None],
        on_progress: Callable[[DownloadTask, object], None],
        on_finished: Callable[[DownloadTask, str], None],
        on_failed: Callable[[DownloadTask, str], None],
        on_all_finished: Callable[[], None],
        history: DownloadHistory,
    ):
        """保存队列回调并初始化线程和取消状态。"""
        self._on_started = on_started
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_failed = on_failed
        self._on_all_finished = on_all_finished
        self._history = history
        self._tasks: list[DownloadTask] = []
        self._current_downloader: VideoDownloader | None = None
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self, tasks: list[DownloadTask], output_dir: str) -> None:
        """启动一组批量下载任务。"""
        if self.is_running():
            raise RuntimeError('下载队列正在运行。')
        self._tasks = tasks
        self._cancel_event.clear()
        self._worker = threading.Thread(
            target=self._run,
            args=(output_dir,),
            daemon=True,
            name='media-download-queue',
        )
        self._worker.start()

    def cancel(self) -> None:
        """取消当前下载并阻止后续等待任务继续执行。"""
        self._cancel_event.set()
        if self._current_downloader is not None:
            self._current_downloader.cancel()

    def is_running(self) -> bool:
        """返回下载队列是否仍在后台运行。"""
        return bool(self._worker and self._worker.is_alive())

    def _run(self, output_dir: str) -> None:
        """在后台线程中顺序执行所有任务。"""
        try:
            for task in self._tasks:
                if self._cancel_event.is_set():
                    task.status = '已取消'
                    continue
                existing_file = self._history.find_existing(task.item)
                if existing_file:
                    task.status = '已存在'
                    task.error = str(existing_file)
                    self._on_finished(task, task.item.title)
                    continue
                task.status = '下载中'
                self._on_started(task)
                self._current_downloader = VideoDownloader(
                    lambda progress, current_task=task: self._on_progress(current_task, progress)
                )
                try:
                    title, file_path = self._current_downloader.download(
                        task.item.url, output_dir, task.options
                    )
                    self._history.record_success(task.item, file_path)
                    task.status = '已完成'
                    self._on_finished(task, title)
                except UserCancelledError:
                    task.status = '已取消'
                except Exception as exc:
                    task.status = '失败'
                    task.error = build_friendly_error(exc)
                    self._on_failed(task, task.error)
                finally:
                    self._current_downloader = None
        finally:
            self._on_all_finished()
