# URL 视频下载器

一个独立的 Windows 桌面小工具：输入公开视频 URL、选择保存目录，然后下载视频到本机。

## 功能

- 单个公开视频 URL 下载
- 自动选择最佳视频和音频并合并为 MP4
- 自定义保存目录
- 下载进度、速度和剩余时间
- 取消下载
- 超时重试与断点续传
- 单文件 Windows exe
- exe 内置 `ffmpeg` 和 `ffprobe`

## 源码运行

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_app.py
```

源码运行时需要系统 PATH 中存在 `ffmpeg` 和 `ffprobe`。

## 构建 exe

```powershell
.\build.ps1
```

构建脚本优先复制系统 PATH 中的 `ffmpeg.exe` 和 `ffprobe.exe`；如果不存在，会下载 Windows essentials 版本。最终文件位于：

```text
dist\URLVideoDownloader.exe
```

生成的 exe 已包含 ffmpeg，目标电脑无需再安装 Python、yt-dlp 或 ffmpeg。

## 使用限制

- 默认只下载单个视频，不下载播放列表。
- 登录、会员、私有、年龄限制或 DRM 视频可能无法下载。
- 网站规则经常变化，建议定期升级 yt-dlp 后重新构建。
- 请只下载你有权保存和使用的内容。
