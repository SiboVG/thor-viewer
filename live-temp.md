# Thor Live Temperature — Reverse Engineering Notes

## USB topology (from `thor_live.pcapng`, USBPcap)

The Thor enumerates as a composite USB device, VID `0x1d6b` PID `0x1102`
(generic Linux-gadget IDs; the camera runs a Linux SoC):

| Interface | Class | Purpose |
| --- | --- | --- |
| 0 + 1 | CDC-ACM (protocol 0xFF), EP 0x82 int, EP 0x81/0x01 bulk | Vendor serial command channel (TM THOR's `Uart_Read`/`Uart_Write`) |
| 2 | Still Image 6/1/1, EP 0x83/0x02 bulk, EP 0x84 int | MTP (SD-card sync) |
| 3 | UVC VideoControl | Camera terminal, processing unit, **Extension Unit ID 4**, GUID `a29e7641-de04-47e3-8b2b-f4341aff003b`, 24 controls |
| 4 | UVC VideoStreaming, EP 0x85 bulk | The only video stream |

The VideoStreaming interface advertises exactly **one format**: frame-based
**H.264, 640x480**, 25/30 fps (UVC format descriptor subtype 0x10, GUID
"H264"). There is no YUY2/MJPEG alternative and no second video interface.

## How temperature is transported

Everything arrives on bulk endpoint 0x85 as UVC payloads (2-byte payload
header `02 8x`, FID toggles per frame, EOF set on every payload):

- **Video samples** (~25/s, 16–23 KB each): complete Annex-B H.264 access
  units. Every frame contains SPS+PPS+IDR (all-intra), so decode is
  stateless.
- **Temperature frames** (~2/s, exactly 98316 bytes): 2-byte UVC header,
  10-byte marker `ff 00 ff 00 ff 00 ff 00 ff 00`, then 256x192 uint16
  little-endian Kelvin*10 (`C = value / 10 - 273.15`), 98304 bytes.

The temperature payloads are valid UVC frames, so the Windows UVC driver
assembles and delivers them as "H.264 samples". Any normal decoding pipeline
(Media Foundation, OpenCV, Qt Multimedia) feeds them into the H.264 decoder,
which silently drops them — that is why temperatures never appeared in
decoded frames.

The TM THOR app (`TM THOR.exe` -> `cmsdk.dll` `CInterfaceVideo` ->
`ARUVCLib.dll` `ArCamManager`/`VideoCaptureDiy`) takes raw samples via a data
callback and ships FFmpeg DLLs to decode H.264 itself, which matches this
design.

## Solution implemented in Thor Viewer

Read the **compressed** sample stream instead of decoded frames, then split:

- packet starts with the ff00 marker -> temperature frame
- packet starts with an H.264 start code -> video access unit

Components:

- `src/thor_viewer/backend/thor_stream_demuxer.py` — splits a compressed
  byte stream (or individual samples) into video/temperature events.
- `src/thor_viewer/backend/thor_compressed_capture.py` —
  `ThorCompressedLiveCapture` grabs the compressed sample stream with an
  ffmpeg dshow subprocess
  (`-f dshow -vcodec h264 -i video=... -c copy -copyinkf -f h264 pipe:1`),
  feeds the pipe through the demuxer, decodes video AUs with PyAV's H.264
  decoder for the live preview, and publishes the latest
  `LiveTemperatureFrame`. ffmpeg is found via `THOR_FFMPEG`, `PATH`, or the
  bundled `imageio-ffmpeg` binary.
- `MainWindow` (Windows): uses the compressed capture for the Live tab
  (video + temperature from one device handle); falls back to the legacy
  OpenCV path if it fails. `THOR_DISABLE_COMPRESSED_CAPTURE=1` forces the
  fallback; `THOR_LIVE_TEMPERATURE_PCAP` still selects the USBPcap-tail
  mode.

Transport dead ends, for the record:

- PyAV's own dshow input cannot open the device: `avformat_find_stream_info`
  fails (the `extract_extradata` pass returns AVERROR_INVALIDDATA on a
  temperature packet) and PyAV treats that as fatal, while the ffmpeg CLI
  only warns and streams on.
- OpenCV's MSMF raw mode (`CAP_PROP_FORMAT=-1` open parameter) fails on
  this device ("can't set property 8"); regular MSMF/OpenCV capture decodes
  and discards the temperature packets.
- ffmpeg stream copy without `-copyinkf` writes nothing: the driver never
  flags samples as keyframes, so the copy path waits forever.

## Validation

Offline, against the full 49 MB `thor_live.pcapng` capture
(`scripts/extract_thor_stream.py`):

- 2165 bulk payloads -> 161 temperature frames + 2004 video samples,
  0 unclassified, 0 false markers inside 33 MB of H.264.
- All 2004 video samples decode to 640x480 BGR via FFmpeg.
- Temperatures plausible across the capture (centers 29.6–37.2 °C).

Live, on real hardware (2026-06-12, `scripts/probe_live_compressed.py`):

- 275 decoded video frames + 22 temperature frames in 12 s
  (~25 fps video, ~2 Hz temperature), center ~34.8 °C.
- The TM THOR app was not running: **the temperature frames flow by
  default**, no enable command is required.
- The full GUI path (offscreen `MainWindow`) produced live video and hover
  temperature through `ThorCompressedLiveCapture`.

Re-run live verification any time (Thor connected, no other app using it):

```bash
uv run python scripts/probe_live_compressed.py --seconds 10
```

## Open questions

- The CDC-ACM serial channel protocol (device settings, emissivity, etc.)
  is unexplored. Note: on some plugs interface 0 enumerates as RNDIS
  (driver error) instead of CDC-ACM, so the device has multiple gadget
  configurations.
- Temperature frame rate may be configurable (TM THOR's `SetTempDataParam`,
  or the UVC Extension Unit's 24 controls).
