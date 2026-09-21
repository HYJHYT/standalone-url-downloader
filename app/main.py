"""HY MediaHub 的桌面窗口和用户交互逻辑。"""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.config import (
    APP_NAME,
    resolve_ffmpeg_location,
    resolve_history_database,
    resolve_thumbnail_cache_dir,
)
from app.downloader import DownloadProgress, build_friendly_error
from app.extractor import MediaExtractor
from app.history import DownloadHistory
from app.models import DownloadOptions, DownloadTask, MediaCollection, MediaItem
from app.task_queue import DownloadQueue
from app.thumbnail import clear_thumbnail_cache, get_thumbnail_cache_usage, load_thumbnail_image


class MediaHubWindow:
    """管理媒体解析、列表选择和批量下载的桌面窗口。"""

    def __init__(self, root: tk.Tk):
        """初始化窗口状态、控件和后台事件轮询。"""
        self.root = root
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.detail_thread: threading.Thread | None = None
        self.detail_cancel_event = threading.Event()
        self.thumbnail_thread: threading.Thread | None = None
        self.thumbnail_photo = None
        self.selected_item: MediaItem | None = None
        self.current_page = 1
        self.page_size = 50
        self.detail_generation = 0
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
        self.root.geometry('1080x820')
        self.root.minsize(900, 720)
        self.root.protocol('WM_DELETE_WINDOW', self._handle_close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _build_widgets(self) -> None:
        """创建 URL 输入、媒体列表、队列操作和进度区域。"""
        container = ttk.Frame(self.root, padding=24)
        container.grid(row=0, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)
        # 为视频列表保留最小高度，避免窗口较小时被其他控件挤压成不可见。
        container.rowconfigure(4, weight=1, minsize=180)

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
        list_panel.rowconfigure(0, weight=1, minsize=180)
        columns = ('selected', 'title', 'uploader', 'duration', 'date', 'status')
        self.media_tree = ttk.Treeview(list_panel, columns=columns, show='headings', selectmode='extended')
        headings = {
            'selected': ('选择', 55),
            'title': ('标题', 360),
            'uploader': ('作者', 150),
            'duration': ('时长', 85),
            'date': ('发布时间', 110),
            'status': ('状态', 90),
        }
        for column, (heading, width) in headings.items():
            self.media_tree.heading(column, text=heading)
            self.media_tree.column(column, width=width, anchor='center' if column == 'selected' else 'w')
        self.media_tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(list_panel, orient='vertical', command=self.media_tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.media_tree.configure(yscrollcommand=scrollbar.set)
        self.media_tree.bind('<<TreeviewSelect>>', self._handle_item_selected)
        self.media_tree.bind('<Button-1>', self._toggle_row_selection, add='+')

        detail_panel = ttk.LabelFrame(container, text='媒体详情', padding=8)
        detail_panel.grid(row=3, column=0, sticky='ew', pady=(0, 8))
        detail_panel.columnconfigure(1, weight=1)
        self.thumbnail_preview_label = ttk.Label(detail_panel, text='暂无封面', width=28, anchor='center')
        self.thumbnail_preview_label.grid(row=0, column=0, rowspan=3, padx=(0, 12), sticky='w')
        ttk.Label(detail_panel, textvariable=self.detail_title_value, font=('Microsoft YaHei UI', 10, 'bold')).grid(
            row=0, column=1, sticky='w'
        )
        ttk.Label(detail_panel, textvariable=self.detail_info_value).grid(row=1, column=1, sticky='w', pady=(3, 0))
        ttk.Label(detail_panel, textvariable=self.thumbnail_value, foreground='#666666').grid(
            row=2, column=1, sticky='w', pady=(3, 0)
        )

        selection_row = ttk.Frame(container)
        selection_row.grid(row=5, column=0, sticky='w', pady=(8, 10))
        self.select_all_button = ttk.Button(selection_row, text='全选', command=self._select_all)
        self.select_all_button.grid(row=0, column=0, padx=(0, 8))
        self.clear_selection_button = ttk.Button(selection_row, text='取消选择', command=self._clear_selection)
        self.clear_selection_button.grid(row=0, column=1, padx=(0, 8))
        self.invert_selection_button = ttk.Button(selection_row, text='反选', command=self._invert_selection)
        self.invert_selection_button.grid(row=0, column=2)

        pagination_row = ttk.Frame(container)
        pagination_row.grid(row=6, column=0, sticky='w', pady=(0, 8))
        self.first_page_button = ttk.Button(pagination_row, text='首页', command=lambda: self._change_page(1))
        self.first_page_button.grid(row=0, column=0, padx=(0, 6))
        self.previous_page_button = ttk.Button(pagination_row, text='上一页', command=self._previous_page)
        self.previous_page_button.grid(row=0, column=1, padx=(0, 6))
        self.page_value = tk.StringVar(value='第 1 / 1 页')
        ttk.Label(pagination_row, textvariable=self.page_value).grid(row=0, column=2, padx=(0, 6))
        self.next_page_button = ttk.Button(pagination_row, text='下一页', command=self._next_page)
        self.next_page_button.grid(row=0, column=3, padx=(0, 6))
        self.last_page_button = ttk.Button(pagination_row, text='末页', command=self._last_page)
        self.last_page_button.grid(row=0, column=4, padx=(0, 12))
        ttk.Label(pagination_row, text='每页').grid(row=0, column=5, padx=(0, 5))
        self.page_size_value = tk.StringVar(value='50')
        self.page_size_combo = ttk.Combobox(
            pagination_row, textvariable=self.page_size_value,
            values=('30', '50', '100'), width=5, state='readonly'
        )
        self.page_size_combo.grid(row=0, column=6)
        self.page_size_combo.bind('<<ComboboxSelected>>', self._change_page_size)

        options_row = ttk.Frame(container)
        options_row.grid(row=7, column=0, sticky='w', pady=(0, 8))
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
        output_row.grid(row=8, column=0, sticky='ew', pady=(0, 10))
        output_row.columnconfigure(1, weight=1)
        ttk.Label(output_row, text='保存位置').grid(row=0, column=0, padx=(0, 8))
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_value)
        self.output_entry.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(output_row, text='选择目录', command=self._choose_output_dir)
        self.browse_button.grid(row=0, column=2, padx=(8, 0))

        progress_panel = ttk.LabelFrame(container, text='下载状态', padding=12)
        progress_panel.grid(row=9, column=0, sticky='ew')
        progress_panel.columnconfigure(0, weight=1)
        ttk.Label(progress_panel, textvariable=self.status_value).grid(row=0, column=0, sticky='w')
        self.progress_bar = ttk.Progressbar(progress_panel, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky='ew', pady=(8, 3))
        ttk.Label(progress_panel, textvariable=self.progress_text).grid(row=1, column=1, padx=(10, 0))
        ttk.Label(progress_panel, textvariable=self.detail_value).grid(row=2, column=0, sticky='w')

        button_row = ttk.Frame(container)
        button_row.grid(row=10, column=0, sticky='e', pady=(14, 0))
        self.open_button = ttk.Button(button_row, text='打开目录', command=self._open_output_dir)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.clear_cache_button = ttk.Button(button_row, text='清理封面缓存', command=self._clear_thumbnail_cache)
        self.clear_cache_button.grid(row=0, column=1, padx=(0, 8))
        self.cancel_button = ttk.Button(button_row, text='取消队列', command=self._cancel_queue, state='disabled')
        self.cancel_button.grid(row=0, column=2, padx=(0, 8))
        self.download_button = ttk.Button(button_row, text='下载选中项目', command=self._start_downloads)
        self.download_button.grid(row=0, column=3)
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

    def _clear_thumbnail_cache(self) -> None:
        """显示封面缓存占用并在确认后删除缓存图片。"""
        cache_dir = resolve_thumbnail_cache_dir()
        file_count, total_bytes = get_thumbnail_cache_usage(cache_dir)
        if file_count == 0:
            messagebox.showinfo(APP_NAME, '当前没有封面缓存。')
            return
        size_mb = total_bytes / 1024 / 1024
        should_clear = messagebox.askyesno(
            APP_NAME,
            f'当前封面缓存：{file_count} 个文件，占用 {size_mb:.1f} MB。\n\n'
            '确定删除封面缓存吗？\n下载历史和已下载视频不会被删除。',
        )
        if not should_clear:
            return
        deleted_count, deleted_bytes = clear_thumbnail_cache(cache_dir)
        self.thumbnail_photo = None
        self.thumbnail_preview_label.configure(text='暂无封面', image='')
        self.status_value.set(f'已清理 {deleted_count} 个封面缓存，释放 {deleted_bytes / 1024 / 1024:.1f} MB。')
        messagebox.showinfo(APP_NAME, f'已清理 {deleted_count} 个封面缓存。')

    def _set_busy_state(self, busy: bool) -> None:
        """根据解析或下载状态切换控件可用性。"""
        entry_state = 'disabled' if busy else 'normal'
        self.url_entry.configure(state=entry_state)
        self.parse_button.configure(state='disabled' if busy else 'normal')
        self.output_entry.configure(state=entry_state)
        self.browse_button.configure(state=entry_state)
        self.clear_cache_button.configure(state='disabled' if busy else 'normal')
        self.quality_combo.configure(state='disabled' if busy else 'readonly')
        self.mode_combo.configure(state='disabled' if busy else 'readonly')
        self.thumbnail_check.configure(state=entry_state)
        self.subtitle_check.configure(state=entry_state)
        self.download_button.configure(state='disabled' if busy else 'normal')
        selection_state = 'disabled' if busy else 'normal'
        self.select_all_button.configure(state=selection_state)
        self.clear_selection_button.configure(state=selection_state)
        self.invert_selection_button.configure(state=selection_state)
        self.first_page_button.configure(state=selection_state)
        self.previous_page_button.configure(state=selection_state)
        self.next_page_button.configure(state=selection_state)
        self.last_page_button.configure(state=selection_state)
        self.page_size_combo.configure(state='disabled' if busy else 'readonly')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        if not busy and self.collection is not None:
            total_pages = max(1, (len(self.collection.items) + self.page_size - 1) // self.page_size)
            self._update_pagination_buttons(total_pages)

    def _start_parse(self) -> None:
        """校验 URL 并在后台线程中解析媒体集合。"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.detail_cancel_event.set()
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
        self.selected_item = None
        self.thumbnail_photo = None
        self.thumbnail_preview_label.configure(text='暂无封面', image='')
        for row_id in self.media_tree.get_children():
            self.media_tree.delete(row_id)
        self.row_items.clear()
        self.collection = None

    def _toggle_row_selection(self, event: tk.Event) -> None:
        """点击列表行时切换该视频的勾选状态。"""
        row_id = self.media_tree.identify_row(event.y)
        item = self.row_items.get(row_id)
        if item is None:
            return
        item.selected = not item.selected
        self._refresh_row(row_id, item)

    def _refresh_row(self, row_id: str, item: MediaItem) -> None:
        """刷新列表行的勾选标记和媒体信息。"""
        self.media_tree.item(row_id, values=(
            '☑' if item.selected else '☐',
            item.title,
            item.uploader or '--',
            item.duration_text(),
            item.upload_date,
            item.status,
        ))

    def _show_collection(self, collection: MediaCollection) -> None:
        """将解析结果填充到媒体列表中。"""
        self.collection = collection
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self) -> None:
        """只渲染当前页的视频，并启动当前页详情补全。"""
        if self.collection is None:
            return
        collection = self.collection
        self.detail_cancel_event.set()
        self.detail_generation += 1
        self._clear_tree()
        self.collection = collection
        total_items = len(self.collection.items)
        total_pages = max(1, (total_items + self.page_size - 1) // self.page_size)
        self.current_page = min(max(1, self.current_page), total_pages)
        start_index = (self.current_page - 1) * self.page_size
        page_items = self.collection.items[start_index:start_index + self.page_size]
        self.collection_value.set(
            f'{self.collection.collection_type}：{self.collection.title}    '
            f'共 {total_items} 个视频    第 {self.current_page} / {total_pages} 页'
        )
        for index, item in enumerate(page_items):
            row_id = str(index)
            self.row_items[row_id] = item
            status = item.status if item.detail_status == '已完成' else '详情解析中'
            self.media_tree.insert('', 'end', iid=row_id, values=(
                '☑' if item.selected else '☐',
                item.title, item.uploader or '--', item.duration_text(), item.upload_date, status,
            ))
        self.page_value.set(f'第 {self.current_page} / {total_pages} 页')
        self._update_pagination_buttons(total_pages)
        if page_items:
            self.media_tree.selection_set('0')
        self.status_value.set(f'正在获取第 {self.current_page} 页的视频详情…')
        self._start_detail_enrichment(page_items, self.detail_generation)

    def _update_pagination_buttons(self, total_pages: int) -> None:
        """根据当前页码切换分页按钮状态。"""
        self.first_page_button.configure(state='normal' if self.current_page > 1 else 'disabled')
        self.previous_page_button.configure(state='normal' if self.current_page > 1 else 'disabled')
        self.next_page_button.configure(state='normal' if self.current_page < total_pages else 'disabled')
        self.last_page_button.configure(state='normal' if self.current_page < total_pages else 'disabled')

    def _change_page(self, page: int) -> None:
        """切换到指定页并重新加载该页详情。"""
        if self.collection is None:
            return
        self.current_page = page
        self._render_current_page()

    def _previous_page(self) -> None:
        """切换到上一页。"""
        self._change_page(self.current_page - 1)

    def _next_page(self) -> None:
        """切换到下一页。"""
        self._change_page(self.current_page + 1)

    def _last_page(self) -> None:
        """切换到最后一页。"""
        if self.collection is None:
            return
        total_pages = max(1, (len(self.collection.items) + self.page_size - 1) // self.page_size)
        self._change_page(total_pages)

    def _change_page_size(self, _event: object) -> None:
        """应用新的每页数量并回到第一页。"""
        self.page_size = int(self.page_size_value.get())
        self.current_page = 1
        self._render_current_page()

    def _start_detail_enrichment(self, items: list[MediaItem], generation: int) -> None:
        """启动后台线程补全当前页视频的详细信息。"""
        self.detail_cancel_event.clear()
        self.detail_thread = threading.Thread(
            target=self._run_detail_enrichment,
            args=(items, generation),
            daemon=True,
            name='media-detail-worker',
        )
        self.detail_thread.start()

    def _run_detail_enrichment(self, items: list[MediaItem], generation: int) -> None:
        """后台逐项解析当前页详情并向界面发送更新事件。"""
        extractor = MediaExtractor(resolve_ffmpeg_location())
        total = len(items)
        for index, item in enumerate(items, start=1):
            if self.detail_cancel_event.is_set():
                break
            try:
                item.detail_status = '解析中'
                extractor.enrich_item(item)
                self.event_queue.put(('detail_item', (generation, index, total, item, None)))
            except Exception as exc:
                item.detail_status = '失败'
                self.event_queue.put(('detail_item', (generation, index, total, item, build_friendly_error(exc))))
        self.event_queue.put(('detail_finished', generation))

    def _update_detail_item(self, item: MediaItem, error: str | None) -> None:
        """将一个视频的详情解析结果同步到列表和当前详情面板。"""
        for row_id, row_item in self.row_items.items():
            if row_item is item:
                status = '详情失败' if error else item.status
                self.media_tree.item(row_id, values=(
                    '☑' if item.selected else '☐',
                    item.title, item.uploader or '--', item.duration_text(), item.upload_date, status,
                ))
                break
        if item is self.selected_item:
            self._show_item_detail(item)

    def _show_item_detail(self, item: MediaItem) -> None:
        """更新详情面板文本并按需加载当前视频的封面。"""
        self.detail_title_value.set(item.title)
        self.detail_info_value.set(
            f'作者：{item.uploader or "--"}    时长：{item.duration_text()}    发布时间：{item.upload_date}'
        )
        self.thumbnail_value.set(f'封面：{item.thumbnail}' if item.thumbnail else '该视频未提供封面地址')
        self.thumbnail_preview_label.configure(text='封面加载中…', image='')
        if item.thumbnail:
            self._start_thumbnail_load(item)

    def _start_thumbnail_load(self, item: MediaItem) -> None:
        """在后台线程中加载当前视频封面，避免阻塞桌面界面。"""
        self.thumbnail_thread = threading.Thread(
            target=self._run_thumbnail_load,
            args=(item, item.thumbnail),
            daemon=True,
            name='thumbnail-worker',
        )
        self.thumbnail_thread.start()

    def _run_thumbnail_load(self, item: MediaItem, thumbnail_url: str) -> None:
        """下载或读取封面缓存并将图片对象发送回界面线程。"""
        try:
            image = load_thumbnail_image(
                thumbnail_url, resolve_thumbnail_cache_dir(), item.id, (240, 135)
            )
            self.event_queue.put(('thumbnail_loaded', (item, image, None)))
        except Exception as exc:
            self.event_queue.put(('thumbnail_loaded', (item, None, str(exc))))

    def _handle_item_selected(self, _event: object) -> None:
        """响应媒体列表选择并显示所选视频的详细信息。"""
        selected_rows = self.media_tree.selection()
        if not selected_rows:
            return
        item = self.row_items.get(selected_rows[0])
        if item is None:
            return
        self.selected_item = item
        self._show_item_detail(item)

    def _select_all(self) -> None:
        """选择当前列表中的全部视频。"""
        for row_id, item in self.row_items.items():
            item.selected = True
            self._refresh_row(row_id, item)

    def _clear_selection(self) -> None:
        """清除当前媒体列表的全部选择。"""
        for row_id, item in self.row_items.items():
            item.selected = False
            self._refresh_row(row_id, item)

    def _invert_selection(self) -> None:
        """反转当前媒体列表的选择状态。"""
        for row_id, item in self.row_items.items():
            item.selected = not item.selected
            self._refresh_row(row_id, item)

    def _start_downloads(self) -> None:
        """将选中的媒体项目转换为下载任务并启动队列。"""
        selected_items = [item for item in self.row_items.values() if item.selected]
        output_dir = self.output_value.get().strip()
        if not selected_items:
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
        tasks = [DownloadTask(item, options=options) for item in selected_items]
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
                elif event_name == 'detail_item' and isinstance(payload, tuple):
                    generation, index, total, item, error = payload
                    if generation != self.detail_generation:
                        continue
                    if isinstance(item, MediaItem):
                        self._update_detail_item(item, error)
                        self.collection_value.set(
                            f'{self.collection.collection_type if self.collection else "媒体集合"}：'
                            f'{self.collection.title if self.collection else ""}    详情解析 {index}/{total}'
                        )
                elif event_name == 'detail_finished' and payload == self.detail_generation:
                    if self.collection:
                        self.collection_value.set(
                            f'{self.collection.collection_type}：{self.collection.title}    '
                            f'共 {len(self.collection.items)} 个视频    第 {self.current_page} 页详情完成'
                        )
                    self.status_value.set('详情解析完成，可以选择视频并下载。')
                elif event_name == 'thumbnail_loaded' and isinstance(payload, tuple):
                    item, image, error = payload
                    if item is not self.selected_item:
                        continue
                    if error or image is None:
                        self.thumbnail_preview_label.configure(text='封面加载失败', image='')
                    else:
                        try:
                            from PIL import ImageTk
                            self.thumbnail_photo = ImageTk.PhotoImage(image=image, master=self.root)
                            self.thumbnail_preview_label.configure(image=self.thumbnail_photo, text='')
                        except Exception:
                            self.thumbnail_preview_label.configure(text='无法显示封面', image='')
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
        self.detail_cancel_event.set()
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
