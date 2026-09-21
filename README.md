# HY MediaHub

一个独立的 Windows 桌面媒体采集与批量下载工具：输入视频、用户主页、播放列表或搜索结果 URL，解析视频列表后选择下载。

## 功能

- 单个公开视频 URL 下载
- 用户主页、频道、播放列表和支持的搜索结果页面解析
- 视频列表勾选、全选、取消选择和反选
- 批量下载队列
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
dist\HY-MediaHub.exe
```

生成的 exe 已包含 ffmpeg，目标电脑无需再安装 Python、yt-dlp 或 ffmpeg。

## 使用限制

- 用户主页、搜索结果和播放列表是否可解析，取决于 yt-dlp 对对应网站的支持情况。
- 登录、会员、私有、年龄限制或 DRM 视频可能无法下载。
- 网站规则经常变化，建议定期升级 yt-dlp 后重新构建。
- 请只下载你有权保存和使用的内容。
