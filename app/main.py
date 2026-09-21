"""HY MediaHub 的桌面窗口和用户交互逻辑。"""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.config import APP_NAME, resolve_ffmpeg_location, resolve_history_database
from app.downloader import DownloadProgress, build_friendly_error
from app.extractor import MediaExtractor
from app.history import DownloadHistory
from app.models import DownloadOptions, DownloadTask, MediaCollection, MediaItem
from app.task_queue import DownloadQueue


class MediaHubWindow:
    """管理媒体解析、列表选择和批量下载的桌面窗口。"""

    def __init__(self, root: tk.Tk):
        """初始化窗口状态、控件和后台事件轮询。"""
        self.root = root
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.collection: MediaCollection | None = None
        self.row_items: dict[str, MediaItem] = {}
        self.download_queue: DownloadQueue | None = None
        self.history = DownloadHistory(resolve_history_database())
        self.url_value = tk.StringVar()
        self.output_value = tk.StringVar(value=str(Path.home() / 'Downloads'))
        self.status_value = tk.StringVar(value='请输入视频、用户主页、播放列表或搜索结果 URL')
        self.collection_value = tk.StringVar(value='尚未解析媒体列表')
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value='0.0%')
        self.detail_value = tk.StringVar(value='速度：--    剩余时间：--')
        self.detail_title_value = tk.StringVar(value='未选择视频')
        self.detail_info_value = tk.StringVar(value='选择列表中的视频查看详细信息')
        self.thumbnail_value = tk.StringVar(value='')
        self.quality_value = tk.StringVar(value='best')
        self.mode_value = tk.StringVar(value='video_audio')
        self.thumbnail_option = tk.BooleanVar(value=False)
        self.subtitle_option = tk.BooleanVar(value=False)
        self._build_window()
        self._build_widgets()
        self.root.after(100, self._poll_events)

    def _build_window(self) -> None:
        """配置窗口尺寸、标题和关闭行为。"""
        self.root.title(APP_NAME)
        self.root.geometry('980x680')
        self.root.minsize(820, 560)
        self.root.protocol('WM_DELETE_WINDOW', self._handle_close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _build_widgets(self) -> None:
        """创建 URL 输入、媒体列表、队列操作和进度区域。"""
        container = ttk.Frame(self.root, padding=24)
        container.grid(row=0, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        ttk.Label(container, text=APP_NAME, font=('Microsoft YaHei UI', 20, 'bold')).grid(
            row=0, column=0, sticky='w', pady=(0, 16)
        )
        url_row = ttk.Frame(container)
        url_row.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        url_row.columnconfigure(0, weight=1)
        ttk.Label(url_row, text='媒体 URL').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 5))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_value)
        self.url_entry.grid(row=1, column=0, sticky='ew')
        self.parse_button = ttk.Button(url_row, text='解析列表', command=self._start_parse)
        self.parse_button.grid(row=1, column=1, padx=(10, 0))

        ttk.Label(container, textvariable=self.collection_value).grid(
            row=2, column=0, sticky='w', pady=(0, 8)
        )
        list_panel = ttk.Frame(container)
        list_panel.grid(row=4, column=0, sticky='nsew')
        list_panel.columnconfigure(0, weight=1)
        list_panel.rowconfigure(0, weight=1)
        columns = ('title', 'uploader', 'duration', 'date', 'status')
        self.media_tree = ttk.Treeview(list_panel, columns=columns, show='headings', selectmode='extended')
        headings = {
            'title': ('标题', 360),
            'uploader': ('作者', 150),
            'duration': ('时长', 85),
            'date': ('发布时间', 110),
            'status': ('状态', 90),
        }
        for column, (heading, width) in headings.items():
            self.media_tree.heading(column, text=heading)
            self.media_tree.column(column, width=width, anchor='w')
        self.media_tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(list_panel, orient='vertical', command=self.media_tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.media_tree.configure(yscrollcommand=scrollbar.set)
        self.media_tree.bind('<<TreeviewSelect>>', self._handle_item_selected)

        detail_panel = ttk.LabelFrame(container, text='媒体详情', padding=8)
        detail_panel.grid(row=3, column=0, sticky='ew', pady=(0, 8))
        detail_panel.columnconfigure(0, weight=1)
        ttk.Label(detail_panel, textvariable=self.detail_title_value, font=('Microsoft YaHei UI', 10, 'bold')).grid(
            row=0, column=0, sticky='w'
        )
        ttk.Label(detail_panel, textvariable=self.detail_info_value).grid(row=1, column=0, sticky='w', pady=(3, 0))
        ttk.Label(detail_panel, textvariable=self.thumbnail_value, foreground='#666666').grid(
            row=2, column=0, sticky='w', pady=(3, 0)
        )

        selection_row = ttk.Frame(container)
        selection_row.grid(row=5, column=0, sticky='w', pady=(8, 10))
        self.select_all_button = ttk.Button(selection_row, text='全选', command=self._select_all)
        self.select_all_button.grid(row=0, column=0, padx=(0, 8))
        self.clear_selection_button = ttk.Button(selection_row, text='取消选择', command=self._clear_selection)
        self.clear_selection_button.grid(row=0, column=1, padx=(0, 8))
        self.invert_selection_button = ttk.Button(selection_row, text='反选', command=self._invert_selection)
        self.invert_selection_button.grid(row=0, column=2)

        options_row = ttk.Frame(container)
        options_row.grid(row=6, column=0, sticky='w', pady=(0, 8))
        ttk.Label(options_row, text='画质').grid(row=0, column=0, padx=(0, 5))
        self.quality_combo = ttk.Combobox(
            options_row, textvariable=self.quality_value,
            values=('best', '2160', '1440', '1080', '720'), width=8, state='readonly'
        )
        self.quality_combo.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(options_row, text='模式').grid(row=0, column=2, padx=(0, 5))
        self.mode_combo = ttk.Combobox(
            options_row, textvariable=self.mode_value,
            values=('video_audio', 'video', 'audio'), width=13, state='readonly'
        )
        self.mode_combo.grid(row=0, column=3, padx=(0, 12))
        self.thumbnail_check = ttk.Checkbutton(options_row, text='下载封面', variable=self.thumbnail_option)
        self.thumbnail_check.grid(row=0, column=4, padx=(0, 10))
        self.subtitle_check = ttk.Checkbutton(options_row, text='下载字幕', variable=self.subtitle_option)
        self.subtitle_check.grid(row=0, column=5)

        output_row = ttk.Frame(container)
        output_row.grid(row=7, column=0, sticky='ew', pady=(0, 10))
        output_row.columnconfigure(1, weight=1)
        ttk.Label(output_row, text='保存位置').grid(row=0, column=0, padx=(0, 8))
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_value)
        self.output_entry.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(output_row, text='选择目录', command=self._choose_output_dir)
        self.browse_button.grid(row=0, column=2, padx=(8, 0))

        progress_panel = ttk.LabelFrame(container, text='下载状态', padding=12)
        progress_panel.grid(row=8, column=0, sticky='ew')
        progress_panel.columnconfigure(0, weight=1)
        ttk.Label(progress_panel, textvariable=self.status_value).grid(row=0, column=0, sticky='w')
        self.progress_bar = ttk.Progressbar(progress_panel, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky='ew', pady=(8, 3))
        ttk.Label(progress_panel, textvariable=self.progress_text).grid(row=1, column=1, padx=(10, 0))
        ttk.Label(progress_panel, textvariable=self.detail_value).grid(row=2, column=0, sticky='w')

        button_row = ttk.Frame(container)
        button_row.grid(row=9, column=0, sticky='e', pady=(14, 0))
        self.open_button = ttk.Button(button_row, text='打开目录', command=self._open_output_dir)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.cancel_button = ttk.Button(button_row, text='取消队列', command=self._cancel_queue, state='disabled')
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        self.download_button = ttk.Button(button_row, text='下载选中项目', command=self._start_downloads)
        self.download_button.grid(row=0, column=2)
        self.url_entry.focus_set()

    def _choose_output_dir(self) -> None:
        """打开目录选择器并保存用户选择的目录。"""
        selected_dir = filedialog.askdirectory(initialdir=self.output_value.get() or str(Path.home()))
        if selected_dir:
            self.output_value.set(selected_dir)

    def _open_output_dir(self) -> None:
        """在 Windows 文件资源管理器中打开保存目录。"""
        output_dir = Path(self.output_value.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir.resolve()))

    def _set_busy_state(self, busy: bool) -> None:
        """根据解析或下载状态切换控件可用性。"""
        entry_state = 'disabled' if busy else 'normal'
        self.url_entry.configure(state=entry_state)
        self.parse_button.configure(state='disabled' if busy else 'normal')
        self.output_entry.configure(state=entry_state)
        self.browse_button.configure(state=entry_state)
        self.quality_combo.configure(state='disabled' if busy else 'readonly')
        self.mode_combo.configure(state='disabled' if busy else 'readonly')
        self.thumbnail_check.configure(state=entry_state)
        self.subtitle_check.configure(state=entry_state)
        self.download_button.configure(state='disabled' if busy else 'normal')
        selection_state = 'disabled' if busy else 'normal'
        self.select_all_button.configure(state=selection_state)
        self.clear_selection_button.configure(state=selection_state)
        self.invert_selection_button.configure(state=selection_state)
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def _start_parse(self) -> None:
        """校验 URL 并在后台线程中解析媒体集合。"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        url = self.url_value.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, '请输入视频、用户主页、播放列表或搜索结果 URL。')
            return
        self._clear_tree()
        self.collection_value.set('正在解析媒体列表…')
        self.status_value.set('正在连接网站并获取视频列表…')
        self._set_busy_state(True)
        self.worker_thread = threading.Thread(target=self._run_parse, args=(url,), daemon=True, name='media-parse-worker')
        self.worker_thread.start()

    def _run_parse(self, url: str) -> None:
        """在后台线程中调用 yt-dlp 解析媒体列表。"""
        try:
            extractor = MediaExtractor(resolve_ffmpeg_location())
            collection = extractor.parse(url)
            self.event_queue.put(('parsed', collection))
        except Exception as exc:
            self.event_queue.put(('parse_failed', build_friendly_error(exc)))

    def _clear_tree(self) -> None:
        """清空媒体列表和对应的项目索引。"""
        for row_id in self.media_tree.get_children():
            self.media_tree.delete(row_id)
        self.row_items.clear()
        self.collection = None

    def _show_collection(self, collection: MediaCollection) -> None:
        """将解析结果填充到媒体列表中。"""
        self._clear_tree()
        self.collection = collection
        self.collection_value.set(
            f'{collection.collection_type}：{collection.title}    共 {len(collection.items)} 个视频'
        )
        for index, item in enumerate(collection.items):
            row_id = str(index)
            self.row_items[row_id] = item
            self.media_tree.insert('', 'end', iid=row_id, values=(
                item.title, item.uploader or '--', item.duration_text(), item.upload_date, item.status,
            ))
        if collection.items:
            self.media_tree.selection_set('0')
        self.status_value.set('解析完成，请选择需要下载的视频。')

    def _handle_item_selected(self, _event: object) -> None:
        """响应媒体列表选择并显示所选视频的详细信息。"""
        selected_rows = self.media_tree.selection()
        if not selected_rows:
            return
        item = self.row_items.get(selected_rows[0])
        if item is None:
            return
        self.detail_title_value.set(item.title)
        self.detail_info_value.set(
            f'作者：{item.uploader or "--"}    时长：{item.duration_text()}    发布时间：{item.upload_date}'
        )
        self.thumbnail_value.set(f'封面：{item.thumbnail}' if item.thumbnail else '该视频未提供封面地址')

    def _select_all(self) -> None:
        """选择当前列表中的全部视频。"""
        self.media_tree.selection_set(self.media_tree.get_children())

    def _clear_selection(self) -> None:
        """清除当前媒体列表的全部选择。"""
        self.media_tree.selection_remove(self.media_tree.selection())

    def _invert_selection(self) -> None:
        """反转当前媒体列表的选择状态。"""
        selected = set(self.media_tree.selection())
        all_rows = self.media_tree.get_children()
        self.media_tree.selection_set([row_id for row_id in all_rows if row_id not in selected])

    def _start_downloads(self) -> None:
        """将选中的媒体项目转换为下载任务并启动队列。"""
        selected_rows = self.media_tree.selection()
        output_dir = self.output_value.get().strip()
        if not selected_rows:
            messagebox.showwarning(APP_NAME, '请先选择至少一个视频。')
            return
        if not output_dir:
            messagebox.showwarning(APP_NAME, '请选择保存目录。')
            return
        if resolve_ffmpeg_location() is None:
            messagebox.showerror(APP_NAME, '未找到 ffmpeg 和 ffprobe，请重新构建程序。')
            return
        options = DownloadOptions(
            quality=self.quality_value.get(),
            mode=self.mode_value.get(),
            write_thumbnail=self.thumbnail_option.get(),
            write_subtitles=self.subtitle_option.get(),
            embed_thumbnail=self.thumbnail_option.get(),
        )
        tasks = [DownloadTask(self.row_items[row_id], options=options) for row_id in selected_rows]
        self.download_queue = DownloadQueue(
            on_started=lambda task: self.event_queue.put(('task_started', task)),
            on_progress=lambda task, progress: self.event_queue.put(('task_progress', (task, progress))),
            on_finished=lambda task, title: self.event_queue.put(('task_finished', (task, title))),
            on_failed=lambda task, error: self.event_queue.put(('task_failed', (task, error))),
            on_all_finished=lambda: self.event_queue.put(('queue_finished', None)),
            history=self.history,
        )
        self._set_busy_state(True)
        self.status_value.set(f'已加入 {len(tasks)} 个下载任务。')
        self.download_queue.start(tasks, output_dir)

    def _update_item_status(self, task: DownloadTask) -> None:
        """同步列表中对应视频的下载状态。"""
        for row_id, item in self.row_items.items():
            if item is task.item:
                item.status = task.status
                self.media_tree.set(row_id, 'status', task.status)
                break

    def _apply_progress(self, progress: DownloadProgress) -> None:
        """将下载进度更新显示到窗口。"""
        self.progress_value.set(progress.percentage)
        self.progress_text.set(f'{progress.percentage:.1f}%')
        self.detail_value.set(f'速度：{progress.speed_text}    剩余时间：{progress.eta_text}')
        self.status_value.set(f'正在下载：{progress.title}')

    def _poll_events(self) -> None:
        """定时处理解析线程和下载队列发送给界面的事件。"""
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                if event_name == 'parsed' and isinstance(payload, MediaCollection):
                    self._show_collection(payload)
                    self._set_busy_state(False)
                elif event_name == 'parse_failed':
                    self.collection_value.set('解析失败')
                    self.status_value.set(str(payload))
                    self._set_busy_state(False)
                    messagebox.showerror(APP_NAME, str(payload))
                elif event_name == 'task_started' and isinstance(payload, DownloadTask):
                    self._update_item_status(payload)
                    self.status_value.set(f'开始下载：{payload.item.title}')
                    self.progress_value.set(0.0)
                    self.progress_text.set('0.0%')
                elif event_name == 'task_progress' and isinstance(payload, tuple):
                    _task, progress = payload
                    if isinstance(progress, DownloadProgress):
                        self._apply_progress(progress)
                elif event_name == 'task_finished' and isinstance(payload, tuple):
                    task, _title = payload
                    self._update_item_status(task)
                elif event_name == 'task_failed' and isinstance(payload, tuple):
                    task, error = payload
                    self._update_item_status(task)
                    self.status_value.set(f'任务失败：{task.item.title}')
                    messagebox.showerror(APP_NAME, str(error))
                elif event_name == 'queue_finished':
                    self._set_busy_state(False)
                    self.status_value.set('下载队列已完成。')
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _cancel_queue(self) -> None:
        """取消当前下载任务并停止后续队列任务。"""
        if self.download_queue is not None:
            self.status_value.set('正在取消下载队列…')
            self.download_queue.cancel()
            self.cancel_button.configure(state='disabled')

    def _handle_close(self) -> None:
        """关闭窗口前确认是否需要取消正在执行的队列。"""
        if self.download_queue and self.download_queue.is_running():
            should_close = messagebox.askyesno(APP_NAME, '下载队列仍在运行，确定取消并退出吗？')
            if not should_close:
                return
            self.download_queue.cancel()
        self.root.destroy()


def enable_windows_dpi_awareness() -> None:
    """在 Windows 上启用高 DPI 适配，失败时保持系统默认行为。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        return


def main() -> None:
    """创建并运行 HY MediaHub 桌面窗口。"""
    enable_windows_dpi_awareness()
    root = tk.Tk()
    ttk.Style(root).theme_use('vista')
    MediaHubWindow(root)
    root.mainloop()
