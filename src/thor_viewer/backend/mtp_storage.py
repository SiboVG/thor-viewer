from __future__ import annotations

import base64
import json
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from threading import Event


class MtpDisconnectedError(RuntimeError):
    pass


class MtpNotFoundError(RuntimeError):
    pass


class MtpToolMissingError(RuntimeError):
    pass


class MtpCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class MtpFile:
    file_id: int
    filename: str
    size: int
    source_path: str | None = None

    @property
    def is_image(self) -> bool:
        return self.filename.lower().endswith((".jpg", ".jpeg", ".png"))

    @property
    def is_ir(self) -> bool:
        return self.filename.endswith("-IR.jpg")

    @property
    def is_dc(self) -> bool:
        return self.filename.endswith("-DC.jpg")

    @property
    def capture_base(self) -> str:
        return self.filename.removesuffix("-IR.jpg").removesuffix("-DC.jpg")


@dataclass(frozen=True)
class CapturePair:
    base: str
    ir: MtpFile | None
    dc: MtpFile | None


_FILE_ID_RE = re.compile(r"^\s*File ID:\s*(\d+)")
_FILENAME_RE = re.compile(r"^\s*Filename:\s*(.+?)\s*$")
_SIZE_RE = re.compile(r"^\s*File size\s+(\d+)")
_CLIXML_ESCAPE_RE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def missing_tool_message(command: str) -> str:
    return (
        f"Storage sync needs MTP support, but `{command}` is not available. "
        "Live view will still work. On Windows, Thor Viewer uses the built-in portable "
        "device bridge. On macOS and Linux, install libmtp-compatible tools that provide "
        "`mtp-files` and `mtp-getfile`, or copy captures from the Thor with another app."
    )


def ensure_mtp_tool(command: str) -> None:
    if shutil.which(command) is None:
        raise MtpToolMissingError(missing_tool_message(command))


def run_command(args: list[str], cancel_event: Event | None = None) -> str:
    ensure_mtp_tool(args[0])

    if cancel_event is None:
        try:
            result = subprocess.run(
                args,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise MtpToolMissingError(missing_tool_message(args[0])) from exc

        output = result.stdout or ""
        returncode = result.returncode
    else:
        try:
            process = subprocess.Popen(
                args,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise MtpToolMissingError(missing_tool_message(args[0])) from exc

        while process.poll() is None:
            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)

                raise MtpCancelledError("MTP command cancelled")

            time.sleep(0.05)

        output, _ = process.communicate()
        output = output or ""
        returncode = process.returncode

    if "No devices" in output or "No Devices have been found" in output:
        raise MtpNotFoundError("No Thor MTP device found")

    if returncode != 0:
        raise RuntimeError(output)

    return output


def _windows_missing_powershell_message() -> str:
    return (
        "Storage sync needs Windows PowerShell for the built-in portable device bridge, "
        "but `powershell.exe` is not available. Live view will still work."
    )


def _encoded_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _decode_clixml_text(text: str) -> str:
    return _CLIXML_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), text)


def _clean_powershell_output(output: str) -> str:
    output = output.strip()
    if not output.startswith("#< CLIXML"):
        return output

    xml_start = output.find("<Objs")
    if xml_start < 0:
        return output

    try:
        root = ET.fromstring(output[xml_start:])
    except ET.ParseError:
        return output

    messages: list[str] = []
    for element in root.iter():
        if element.tag.endswith("S") and element.attrib.get("S") == "Error" and element.text:
            messages.append(_decode_clixml_text(element.text).strip())

    return "\n".join(message for message in messages if message) or output


def run_windows_powershell_json(
    script: str,
    cancel_event: Event | None = None,
) -> object:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise MtpToolMissingError(_windows_missing_powershell_message())

    args = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-OutputFormat",
        "Text",
        "-EncodedCommand",
        _encoded_powershell(script),
    ]

    if cancel_event is None:
        try:
            result = subprocess.run(
                args,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise MtpToolMissingError(_windows_missing_powershell_message()) from exc

        output = _clean_powershell_output(result.stdout or "")
        returncode = result.returncode
    else:
        output, returncode = _run_cancellable_process(args, cancel_event)

    if "No Thor MTP device found" in output:
        raise MtpNotFoundError("No Thor MTP device found")

    if returncode != 0:
        raise RuntimeError(output)

    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(output) from exc


def _run_cancellable_process(args: list[str], cancel_event: Event) -> tuple[str, int]:
    try:
        process = subprocess.Popen(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise MtpToolMissingError(_windows_missing_powershell_message()) from exc

    while True:
        try:
            output, _ = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if not cancel_event.is_set():
                continue

            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)

            raise MtpCancelledError("Windows MTP command cancelled")

    return _clean_powershell_output(output or ""), process.returncode


def _parse_windows_files(payload: object) -> list[MtpFile]:
    if payload is None:
        return []

    items = payload if isinstance(payload, list) else [payload]
    files: list[MtpFile] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            files.append(
                MtpFile(
                    file_id=int(item["FileId"]),
                    filename=str(item["Filename"]),
                    size=int(item["Size"] or 0),
                    source_path=str(item["SourcePath"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return files


class _MtpStorageBase:
    def list_files(self, cancel_event: Event | None = None) -> list[MtpFile]:
        raise NotImplementedError

    def download_file(
        self,
        file: MtpFile,
        output_dir: Path,
        skip_existing: bool = True,
        retries: int = 3,
        cancel_event: Event | None = None,
    ) -> Path | None:
        raise NotImplementedError

    def list_capture_pairs(self, cancel_event: Event | None = None) -> list[CapturePair]:
        image_files = [f for f in self.list_files(cancel_event=cancel_event) if f.is_image]

        grouped: dict[str, dict[str, MtpFile]] = {}

        for file in image_files:
            grouped.setdefault(file.capture_base, {})

            if file.is_ir:
                grouped[file.capture_base]["ir"] = file
            elif file.is_dc:
                grouped[file.capture_base]["dc"] = file

        pairs = [
            CapturePair(
                base=base,
                ir=items.get("ir"),
                dc=items.get("dc"),
            )
            for base, items in grouped.items()
        ]

        return sorted(pairs, key=lambda p: p.base, reverse=True)

    def download_pair(self, pair: CapturePair, output_dir: Path) -> list[Path]:
        paths: list[Path] = []

        for file in (pair.ir, pair.dc):
            if file is None:
                continue

            path = self.download_file(file, output_dir)
            if path is not None:
                paths.append(path)

        return paths


class LibMtpCliStorage(_MtpStorageBase):
    def list_files(self, cancel_event: Event | None = None) -> list[MtpFile]:
        output = run_command(["mtp-files"], cancel_event=cancel_event)

        files: list[MtpFile] = []
        current_id: int | None = None
        current_name: str | None = None
        current_size: int | None = None

        def flush_current() -> None:
            nonlocal current_id, current_name, current_size

            if current_id is not None and current_name is not None and current_size is not None:
                files.append(MtpFile(current_id, current_name, current_size))

            current_id = None
            current_name = None
            current_size = None

        for line in output.splitlines():
            if match := _FILE_ID_RE.search(line):
                flush_current()
                current_id = int(match.group(1))

            elif match := _FILENAME_RE.search(line):
                current_name = match.group(1).strip()

            elif match := _SIZE_RE.search(line):
                current_size = int(match.group(1))

        flush_current()

        return files

    def download_file(
        self,
        file: MtpFile,
        output_dir: Path,
        skip_existing: bool = True,
        retries: int = 3,
        cancel_event: Event | None = None,
    ) -> Path | None:
        ensure_mtp_tool("mtp-getfile")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / file.filename

        if skip_existing and output_path.exists() and output_path.stat().st_size == file.size:
            return output_path

        for _ in range(retries):
            if cancel_event is not None and cancel_event.is_set():
                return None

            if output_path.exists():
                output_path.unlink()

            try:
                process = subprocess.Popen(
                    ["mtp-getfile", str(file.file_id), str(output_path)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except FileNotFoundError as exc:
                raise MtpToolMissingError(missing_tool_message("mtp-getfile")) from exc

            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1.0)

                    if output_path.exists():
                        output_path.unlink()

                    return None

                time.sleep(0.05)

            output, _ = process.communicate()
            output = output or ""

            if "No devices" in output or "No Devices have been found" in output:
                raise MtpDisconnectedError("Thor disconnected during transfer")

            if output_path.exists() and output_path.stat().st_size == file.size:
                return output_path

        return None


_WINDOWS_LIST_FILES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$shell = New-Object -ComObject Shell.Application
$root = $shell.Namespace(17)
if ($null -eq $root) {
    throw 'Windows Shell This PC namespace is unavailable'
}

$device = @($root.Items() | Where-Object {
    $_.IsFolder -and ($_.Name -like '*Thor*' -or $_.Type -eq 'Portable Device')
} | Where-Object {
    $_.Name -like '*Thor*'
} | Select-Object -First 1)

if ($null -eq $device) {
    throw 'No Thor MTP device found'
}

function Get-ChildByName($item, [string]$name) {
    $folder = $item.GetFolder
    if ($null -eq $folder) {
        return $null
    }

    return @($folder.Items() | Where-Object { $_.Name -eq $name } | Select-Object -First 1)
}

$start = $device
$prefix = ''
$recursive = $true
$storage = Get-ChildByName $device 'STORAGE'
if ($null -ne $storage) {
    $start = $storage
    $prefix = $storage.Name

    $dcim = Get-ChildByName $storage 'DCIM'
    if ($null -ne $dcim) {
        $start = $dcim
        $prefix = "$($storage.Name)/$($dcim.Name)"
        $recursive = $false
    }
}

$script:files = New-Object System.Collections.ArrayList
$script:fileId = 1

function Add-Files($item, [string]$pathPrefix) {
    $folder = $item.GetFolder
    if ($null -eq $folder) {
        return
    }

    foreach ($child in @($folder.Items())) {
        if ([string]::IsNullOrEmpty($pathPrefix)) {
            $sourcePath = $child.Name
        } else {
            $sourcePath = "$pathPrefix/$($child.Name)"
        }

        if ($child.IsFolder) {
            Add-Files $child $sourcePath
        } else {
            $size = $child.ExtendedProperty('System.Size')
            if ($null -eq $size) {
                $size = $child.ExtendedProperty('Size')
            }
            if ($null -eq $size) {
                $size = 0
            }

            [void]$script:files.Add([PSCustomObject]@{
                FileId = $script:fileId
                Filename = $child.Name
                Size = [Int64]$size
                SourcePath = $sourcePath
            })
            $script:fileId += 1
        }
    }
}

function Add-ImmediateFiles($item, [string]$pathPrefix) {
    $folder = $item.GetFolder
    if ($null -eq $folder) {
        return
    }

    foreach ($child in @($folder.Items())) {
        if ($child.IsFolder) {
            continue
        }

        if ([string]::IsNullOrEmpty($pathPrefix)) {
            $sourcePath = $child.Name
        } else {
            $sourcePath = "$pathPrefix/$($child.Name)"
        }

        $size = $child.ExtendedProperty('System.Size')
        if ($null -eq $size) {
            $size = $child.ExtendedProperty('Size')
        }
        if ($null -eq $size) {
            $size = 0
        }

        [void]$script:files.Add([PSCustomObject]@{
            FileId = $script:fileId
            Filename = $child.Name
            Size = [Int64]$size
            SourcePath = $sourcePath
        })
        $script:fileId += 1
    }
}

if ($recursive) {
    Add-Files $start $prefix
} else {
    Add-ImmediateFiles $start $prefix
}
@($script:files.ToArray()) | ConvertTo-Json -Compress
"""


class WindowsShellMtpStorage(_MtpStorageBase):
    def list_files(self, cancel_event: Event | None = None) -> list[MtpFile]:
        payload = run_windows_powershell_json(
            _WINDOWS_LIST_FILES_SCRIPT,
            cancel_event=cancel_event,
        )
        return _parse_windows_files(payload)

    def download_file(
        self,
        file: MtpFile,
        output_dir: Path,
        skip_existing: bool = True,
        retries: int = 3,
        cancel_event: Event | None = None,
    ) -> Path | None:
        if file.source_path is None:
            raise RuntimeError("Windows MTP file is missing a source path")

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / file.filename

        if skip_existing and output_path.exists() and output_path.stat().st_size == file.size:
            return output_path

        for _ in range(retries):
            if cancel_event is not None and cancel_event.is_set():
                return None

            if output_path.exists():
                output_path.unlink()

            payload = run_windows_powershell_json(
                self._download_script(file, output_dir),
                cancel_event=cancel_event,
            )

            if not isinstance(payload, dict):
                continue

            copied_size = int(payload.get("Size") or 0)
            if output_path.exists() and copied_size == file.size:
                return output_path

        return None

    def _download_script(self, file: MtpFile, output_dir: Path) -> str:
        source_path = base64.b64encode((file.source_path or "").encode("utf-8")).decode("ascii")
        target_dir = base64.b64encode(str(output_dir).encode("utf-8")).decode("ascii")
        expected_size = file.size

        return rf"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$sourcePath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{source_path}'))
$outputDir = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{target_dir}'))
$expectedSize = [Int64]{expected_size}

$shell = New-Object -ComObject Shell.Application
$root = $shell.Namespace(17)
if ($null -eq $root) {{
    throw 'Windows Shell This PC namespace is unavailable'
}}

$device = @($root.Items() | Where-Object {{
    $_.IsFolder -and ($_.Name -like '*Thor*' -or $_.Type -eq 'Portable Device')
}} | Where-Object {{
    $_.Name -like '*Thor*'
}} | Select-Object -First 1)

if ($null -eq $device) {{
    throw 'No Thor MTP device found'
}}

function Resolve-PortableItem($item, [string]$relativePath) {{
    $current = $item
    foreach ($part in $relativePath -split '/') {{
        if ([string]::IsNullOrEmpty($part)) {{
            continue
        }}

        $folder = $current.GetFolder
        if ($null -eq $folder) {{
            throw "Portable path is not a folder before segment: $part"
        }}

        $next = @($folder.Items() | Where-Object {{ $_.Name -eq $part }} | Select-Object -First 1)
        if ($null -eq $next) {{
            throw "Portable path segment not found: $part"
        }}

        $current = $next
    }}

    return $current
}}

$source = Resolve-PortableItem $device $sourcePath
$destination = $shell.Namespace($outputDir)
if ($null -eq $destination) {{
    throw "Destination folder is unavailable: $outputDir"
}}

$targetPath = Join-Path $outputDir $source.Name
$destination.CopyHere($source, 16)

$deadline = (Get-Date).AddSeconds(60)
$lastSize = -1
$stableCount = 0
while ((Get-Date) -lt $deadline) {{
    if (Test-Path -LiteralPath $targetPath) {{
        $actualSize = (Get-Item -LiteralPath $targetPath).Length
        if ($expectedSize -gt 0 -and $actualSize -eq $expectedSize) {{
            break
        }}

        if ($expectedSize -le 0 -and $actualSize -gt 0) {{
            if ($actualSize -eq $lastSize) {{
                $stableCount += 1
            }} else {{
                $stableCount = 0
                $lastSize = $actualSize
            }}

            if ($stableCount -ge 5) {{
                break
            }}
        }}
    }}

    Start-Sleep -Milliseconds 200
}}

if (-not (Test-Path -LiteralPath $targetPath)) {{
    throw "Copy did not create output file: $targetPath"
}}

$finalSize = (Get-Item -LiteralPath $targetPath).Length
[PSCustomObject]@{{
    Path = $targetPath
    Size = [Int64]$finalSize
}} | ConvertTo-Json -Compress
"""


class MtpStorage:
    def __init__(self, backend: _MtpStorageBase | None = None) -> None:
        self._backend = backend or self._default_backend()

    @staticmethod
    def _default_backend() -> _MtpStorageBase:
        if platform.system() == "Windows":
            return WindowsShellMtpStorage()

        return LibMtpCliStorage()

    def list_files(self, cancel_event: Event | None = None) -> list[MtpFile]:
        return self._backend.list_files(cancel_event=cancel_event)

    def list_capture_pairs(self, cancel_event: Event | None = None) -> list[CapturePair]:
        return self._backend.list_capture_pairs(cancel_event=cancel_event)

    def download_file(
        self,
        file: MtpFile,
        output_dir: Path,
        skip_existing: bool = True,
        retries: int = 3,
        cancel_event: Event | None = None,
    ) -> Path | None:
        return self._backend.download_file(
            file,
            output_dir,
            skip_existing=skip_existing,
            retries=retries,
            cancel_event=cancel_event,
        )

    def download_pair(self, pair: CapturePair, output_dir: Path) -> list[Path]:
        return self._backend.download_pair(pair, output_dir)
