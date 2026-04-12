Drop bundled runtime dependencies here.

Expected layout:
- `vendor/site-packages/` for Python packages such as `av`
- `vendor/bin/` for native DLLs required by bundled wheels
  - include FFmpeg DLLs from the PyAV wheel
  - include `python3.dll` plus `vcruntime140*.dll` when the host embeds Python without the stable-ABI/runtime DLLs on its search path

The plugin bootstraps this directory into `sys.path` and `os.add_dll_directory()` during `init()`.
