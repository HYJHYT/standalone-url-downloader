import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.config import APP_NAME, resolve_ffmpeg_location
from app.downloader import DownloadProgress, UserCancelledError, VideoDownloader, build_friendly_error


class DownloaderWindow:
    """管理独立 URL 视频下载器的桌面窗口。"""

    def __init__(self, root: tk.Tk):
        """初始化窗口状态、控件和后台事件轮询。"""
        self.root = root
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.downloader: VideoDownloader | None = None
        self.worker_thread: threading.Thread | None = None
        self.url_value = tk.StringVar()
        self.output_value = tk.StringVar(value=str(Path.home() / 'Downloads'))
        self.title_value = tk.StringVar(value='等待下载')
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value='0.0%')
        self.detail_value = tk.StringVar(value='速度：--    剩余时间：--')
        self.status_value = tk.StringVar(value='请输入视频 URL 并选择保存位置')
        self._build_window()
        self._build_widgets()
        self.root.after(100, self._poll_events)

    def _build_window(self) -> None:
        """配置窗口尺寸、标题和关闭行为。"""
        self.root.title(APP_NAME)
        self.root.geometry('720x470')
        self.root.minsize(640, 430)
        self.root.protocol('WM_DELETE_WINDOW', self._handle_close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _build_widgets(self) -> None:
        """创建 URL、保存目录、下载进度和操作按钮。"""
        container = ttk.Frame(self.root, padding=28)
        container.grid(row=0, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)

        ttk.Label(container, text=APP_NAME, font=('Microsoft YaHei UI', 20, 'bold')).grid(
            row=0, column=0, sticky='w', pady=(0, 22)
        )
        ttk.Label(container, text='视频 URL').grid(row=1, column=0, sticky='w', pady=(0, 6))
        self.url_entry = ttk.Entry(container, textvariable=self.url_value)
        self.url_entry.grid(row=2, column=0, sticky='ew', pady=(0, 16))

        ttk.Label(container, text='保存位置').grid(row=3, column=0, sticky='w', pady=(0, 6))
        output_row = ttk.Frame(container)
        output_row.grid(row=4, column=0, sticky='ew', pady=(0, 22))
        output_row.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_value)
        self.output_entry.grid(row=0, column=0, sticky='ew')
        self.browse_button = ttk.Button(output_row, text='选择目录', command=self._choose_output_dir)
        self.browse_button.grid(row=0, column=1, padx=(10, 0))

        progress_panel = ttk.LabelFrame(container, text='下载状态', padding=16)
        progress_panel.grid(row=5, column=0, sticky='ew')
        progress_panel.columnconfigure(0, weight=1)
        ttk.Label(progress_panel, textvariable=self.title_value).grid(row=0, column=0, sticky='w')
        self.progress_bar = ttk.Progressbar(progress_panel, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky='ew', pady=(12, 4))
        ttk.Label(progress_panel, textvariable=self.progress_text).grid(row=1, column=1, padx=(12, 0))
        ttk.Label(progress_panel, textvariable=self.detail_value).grid(row=2, column=0, sticky='w', pady=(6, 0))
        ttk.Label(progress_panel, textvariable=self.status_value).grid(row=3, column=0, columnspan=2, sticky='w', pady=(8, 0))

        button_row = ttk.Frame(container)
        button_row.grid(row=6, column=0, sticky='e', pady=(22, 0))
        self.open_button = ttk.Button(button_row, text='打开目录', command=self._open_output_dir)
        self.open_button.grid(row=0, column=0, padx=(0, 10))
        self.cancel_button = ttk.Button(button_row, text='取消下载', command=self._cancel_download, state='disabled')
        self.cancel_button.grid(row=0, column=1, padx=(0, 10))
        self.start_button = ttk.Button(button_row, text='开始下载', command=self._start_download)
        self.start_button.grid(row=0, column=2)
        self.url_entry.focus_set()

    def _choose_output_dir(self) -> None:
        """打开系统目录选择器并保存用户选择。"""
        selected_dir = filedialog.askdirectory(initialdir=self.output_value.get() or str(Path.home()))
        if selected_dir:
            self.output_value.set(selected_dir)

    def _open_output_dir(self) -> None:
        """在 Windows 文件资源管理器中打开保存目录。"""
        output_dir = Path(self.output_value.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir.resolve()))

    def _set_running_state(self, running: bool) -> None:
        """根据下载状态切换表单和按钮的可用性。"""
        entry_state = 'disabled' if running else 'normal'
        self.url_entry.configure(state=entry_state)
        self.output_entry.configure(state=entry_state)
        self.browse_button.configure(state=entry_state)
        self.start_button.configure(state='disabled' if running else 'normal')
        self.cancel_button.configure(state='normal' if running else 'disabled')

    def _start_download(self) -> None:
        """校验输入并启动后台下载线程。"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if resolve_ffmpeg_location() is None:
            messagebox.showerror(APP_NAME, '未找到 ffmpeg 和 ffprobe，请重新构建程序。')
            return
        url = self.url_value.get().strip()
        output_dir = self.output_value.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, '请输入视频 URL。')
            return
        if not output_dir:
            messagebox.showwarning(APP_NAME, '请选择保存目录。')
            return
        self.progress_value.set(0.0)
        self.progress_text.set('0.0%')
        self.title_value.set('正在解析视频信息')
        self.detail_value.set('速度：--    剩余时间：--')
        self.status_value.set('正在连接视频页面…')
        self._set_running_state(True)
        self.downloader = VideoDownloader(self._queue_progress)
        self.worker_thread = threading.Thread(
            target=self._run_download,
            args=(url, output_dir),
            daemon=True,
            name='video-download-worker',
        )
        self.worker_thread.start()

    def _run_download(self, url: str, output_dir: str) -> None:
        """在后台线程中执行下载并向界面发送结束事件。"""
        try:
            if self.downloader is None:
                return
            title = self.downloader.download(url, output_dir)
            self.event_queue.put(('completed', title))
        except UserCancelledError:
            self.event_queue.put(('cancelled', None))
        except Exception as exc:
            self.event_queue.put(('failed', build_friendly_error(exc)))

    def _queue_progress(self, progress: DownloadProgress) -> None:
        """将后台线程的下载进度放入线程安全队列。"""
        self.event_queue.put(('progress', progress))

    def _apply_progress(self, progress: DownloadProgress) -> None:
        """将一次下载进度更新显示到窗口。"""
        self.title_value.set(progress.title)
        self.progress_value.set(progress.percentage)
        self.progress_text.set(f'{progress.percentage:.1f}%')
        self.detail_value.set(f'速度：{progress.speed_text}    剩余时间：{progress.eta_text}')
        status_text = '正在合并音视频…' if progress.status == 'processing' else '正在下载…'
        self.status_value.set(status_text)

    def _poll_events(self) -> None:
        """定时处理后台线程发送给界面的事件。"""
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                if event_name == 'progress' and isinstance(payload, DownloadProgress):
                    self._apply_progress(payload)
                elif event_name == 'completed':
                    self.progress_value.set(100.0)
                    self.progress_text.set('100.0%')
                    self.status_value.set('下载完成')
                    self._set_running_state(False)
                    messagebox.showinfo(APP_NAME, f'“{payload}”下载完成。')
                elif event_name == 'cancelled':
                    self.status_value.set('下载已取消，可稍后重新开始并尝试断点续传')
                    self._set_running_state(False)
                elif event_name == 'failed':
                    self.status_value.set('下载失败')
                    self._set_running_state(False)
                    messagebox.showerror(APP_NAME, str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _cancel_download(self) -> None:
        """通知后台下载器停止当前任务。"""
        if self.downloader is not None:
            self.status_value.set('正在取消下载…')
            self.downloader.cancel()
            self.cancel_button.configure(state='disabled')

    def _handle_close(self) -> None:
        """关闭窗口前确认是否需要取消正在执行的下载。"""
        if self.worker_thread and self.worker_thread.is_alive():
            should_close = messagebox.askyesno(APP_NAME, '下载仍在进行，确定取消并退出吗？')
            if not should_close:
                return
            if self.downloader is not None:
                self.downloader.cancel()
        self.root.destroy()


def enable_windows_dpi_awareness() -> None:
    """在 Windows 上启用高 DPI 适配，失败时保持系统默认行为。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        return


def main() -> None:
    """创建并运行独立下载器桌面窗口。"""
    enable_windows_dpi_awareness()
    root = tk.Tk()
    ttk.Style(root).theme_use('vista')
    DownloaderWindow(root)
    root.mainloop()

