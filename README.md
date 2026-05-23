# Thor Viewer

Thor Viewer is an open-source, cross-platform desktop alternative to Thermal Master's TM Thor PC app. It is built for the ThermalMaster Thor UVC thermal camera and focuses on live viewing, SD-card capture sync, and basic radiometric image analysis.

## Features

- Live UVC camera view with snapshot and recording controls
- Thor SD-card browser with automatic missing-file sync over MTP
- Radiometric JPEG preview and temperature readout
- Analysis tab for downloaded IR captures
- Python/PySide6 app intended to run on macOS, Linux, and Windows

## Requirements

- Python 3.10+
- A ThermalMaster Thor camera
- `uv` for dependency management
- MTP command-line tools available on your platform (`mtp-files`, `mtp-getfile`) for SD-card sync

## Run

```bash
uv sync
uv run thor-viewer
```

If the camera is not detected, open the Live tab, refresh devices, and connect the Thor camera. Open the Storage tab to sync SD-card captures into `thor_downloads/`.

## Development

```bash
uv run python -m compileall src scripts main.py
```

The helper scripts in `scripts/` are for MTP and radiometric JPEG inspection. Downloaded captures, recordings, snapshots, virtual environments, and local IDE files are ignored by git.

## Status

This project is early-stage and reverse-engineered from observed Thor camera files and device behavior. ThermalMaster is a trademark of its owner; this project is independent and not affiliated with ThermalMaster.

## License

MIT
