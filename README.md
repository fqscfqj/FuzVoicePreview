# FUZ Voice Preview

FUZ Voice Preview 是一个面向 Mod Organizer 2 的 Python 预览插件，用于在 MO2 中直接预览和播放 `.fuz` 语音文件。插件会解析 FUZ / FUZE 容器，识别内嵌音频格式，并在可用时自动解码后播放。

## 特性

- 支持本地文件和归档文件预览
- 自动识别 FUZ / FUZE 容器
- 支持内嵌音频格式：WAV、XWMA、Ogg/Opus、WMA、MP3、FLAC、AAC、MP4/M4A
- 提供播放、暂停、停止、拖动定位和音量调节
- 可导出内嵌音频和 LIP 数据
- 内置简体中文、繁体中文、英文及多种主要语言翻译

## 安装

推荐从 GitHub Releases 下载完整发布包，而不是直接克隆源码仓库。

1. 下载 `FuzVoicePreview-release-<version>.zip`。
2. 解压后，将其中的 `FuzVoicePreview` 目录放到 MO2 可以扫描到的 Python 插件目录中。
3. 保留 `FuzVoicePreview/vendor/` 和 `FuzVoicePreview/i18n/` 目录不变。
4. 重启 MO2。

如果你的 MO2 环境已经提供 `mobase` 和 `PyQt6`，完整发布包通常可以直接工作。发布包中包含 PyAV 以及所需的本地 DLL，因此一般不需要额外手动安装这些组件。

源码仓库默认只保留 `FuzVoicePreview/vendor/README.md` 作为目录说明；`vendor/bin/`、`vendor/site-packages/` 和可选的 `vendor/python/` 视为发布期运行时文件，由 GitHub Actions 在 Release 打包时注入。

## 使用

- 在 MO2 中选中 `.fuz` 文件即可看到预览面板。
- 如果开启了自动播放，音频会在解码完成后自动开始播放。
- 你可以在预览界面中调节音量、拖动进度条、暂停或停止播放。
- 需要导出时，点击 `Export Audio` 或 `Export LIP`。

如果 `PyQt6.QtMultimedia` 不可用，插件会尝试使用 Windows MCI 作为后备播放后端；如果两者都不可用，预览仍然可以解析文件，但无法播放音频。

## 设置

插件提供以下设置：

- `autoplay`：解码完成后自动播放
- `default_volume`：默认音量，范围 0 到 100
- `debug_logging`：输出额外运行时诊断信息

## 开发环境

建议使用独立虚拟环境进行本地开发：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

如果你需要做本地 UI 冒烟测试，可以额外安装 `PyQt6`：

```powershell
python -m pip install PyQt6
```

说明：

- 单元测试只依赖 `pytest`，不要求本地安装 MO2 或 `mobase`。
- 如果要在 MO2 中联调插件，需要使用带有 `mobase` 的 MO2 Python 运行环境。
- 如果要构建完整发布包，需要在本地准备好 `FuzVoicePreview/vendor/` 下的运行时依赖，但这些文件默认不再纳入源码仓库版本控制。

## 测试

```powershell
python -m pytest
```

当前测试主要覆盖解析、解码、播放协调和控制器逻辑。

## 发布

当 GitHub 上创建并发布新的 Release 时，仓库中的 GitHub Actions 会自动完成打包并把完整插件包附加到该 Release：

- `FuzVoicePreview-release-<tag>.zip`：完整插件包，压缩包根目录直接是 `FuzVoicePreview/`，其中包含面向当前 MO2 Python 3.11 运行时的 `vendor` 依赖，可直接用于发布。

如果需要重新打包，只要重新运行对应的 Release 工作流即可。

## 依赖说明

- Windows
- Mod Organizer 2
- `mobase`
- `PyQt6`
- PyAV（完整发布包会在 `vendor` 中提供）
