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

1. 将整个 `FuzVoicePreview` 目录放到 MO2 可以扫描到的 Python 插件目录中。通常做法是把这个目录作为插件包直接放入 MO2 的插件加载路径。
2. 保留 `vendor` 目录。这里包含打包好的运行时依赖，插件启动时会自动把它加入 `sys.path` 和 DLL 搜索路径。
3. 保留 `FuzVoicePreview/i18n/` 目录。中文翻译文件现在放在这里。
4. 重启 MO2。

如果你的 MO2 环境已经提供 `mobase` 和 `PyQt6`，插件可以直接工作。仓库里已经打包了 PyAV 等运行时依赖，因此一般不需要额外手动安装这些组件。

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

## 开发与测试

开发环境下可以运行测试：

```bash
python -m pytest
```

仓库中的测试覆盖了解析、解码、播放协调和控制器逻辑。如果本地环境里还没有 `pytest`，请先安装它。

## 依赖说明

- Windows
- Mod Organizer 2
- `mobase`
- `PyQt6`
- PyAV（仓库已在 `vendor` 中打包）
