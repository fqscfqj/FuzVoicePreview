Drop bundled runtime dependencies here.

Expected layout:
- `vendor/site-packages-py310/`, `vendor/site-packages-py311/`, `vendor/site-packages-py312/` for version-specific Python packages such as `av`
- `vendor/site-packages/` as an optional fallback for single-runtime local builds
- `vendor/bin/` for native DLLs required by bundled wheels
  - include FFmpeg DLLs from the PyAV wheel
  - include `python3.dll` plus `vcruntime140*.dll` when the host embeds Python without the stable-ABI/runtime DLLs on its search path

The plugin selects the matching `site-packages-py<major><minor>/` directory for the active MO2 Python runtime, falls back to `vendor/site-packages/` when needed, and then bootstraps the chosen directory into `sys.path` and `os.add_dll_directory()` during `init()`.
