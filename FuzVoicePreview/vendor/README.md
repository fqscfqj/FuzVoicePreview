Drop bundled runtime dependencies here.

Expected layout:
- `vendor/site-packages/` for bundled Python packages such as `av`
- `vendor/bin/` for native DLLs required by bundled wheels
  - include FFmpeg DLLs from the PyAV wheel
  - include `python3.dll` plus `vcruntime140*.dll` when the host embeds Python without the stable-ABI/runtime DLLs on its search path

The plugin prefers a matching `site-packages-py<major><minor>/` directory when one is present, falls back to `vendor/site-packages/` for the single-runtime release bundle, and then bootstraps the chosen directory into `sys.path` and `os.add_dll_directory()` during `init()`.
