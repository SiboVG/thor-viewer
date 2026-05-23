from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event


class MtpDisconnectedError(RuntimeError):
    pass


class MtpNotFoundError(RuntimeError):
    pass


class MtpCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class MtpFile:
    file_id: int
    filename: str
    size: int

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
        return (
            self.filename
            .removesuffix("-IR.jpg")
            .removesuffix("-DC.jpg")
        )


@dataclass(frozen=True)
class CapturePair:
    base: str
    ir: MtpFile | None
    dc: MtpFile | None


_FILE_ID_RE = re.compile(r"^\s*File ID:\s*(\d+)")
_FILENAME_RE = re.compile(r"^\s*Filename:\s*(.+?)\s*$")
_SIZE_RE = re.compile(r"^\s*File size\s+(\d+)")


def run_command(args: list[str], cancel_event: Event | None = None) -> str:
    if cancel_event is None:
        result = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        output = result.stdout or ""
        returncode = result.returncode
    else:
        process = subprocess.Popen(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

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


class MtpStorage:
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

    def download_file(
        self,
        file: MtpFile,
        output_dir: Path,
        skip_existing: bool = True,
        retries: int = 3,
        cancel_event: Event | None = None,
    ) -> Path | None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / file.filename

        if skip_existing and output_path.exists() and output_path.stat().st_size == file.size:
            return output_path

        for _ in range(retries):
            if cancel_event is not None and cancel_event.is_set():
                return None

            if output_path.exists():
                output_path.unlink()

            process = subprocess.Popen(
                ["mtp-getfile", str(file.file_id), str(output_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

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

    def download_pair(self, pair: CapturePair, output_dir: Path) -> list[Path]:
        paths: list[Path] = []

        for file in (pair.ir, pair.dc):
            if file is None:
                continue

            path = self.download_file(file, output_dir)
            if path is not None:
                paths.append(path)

        return paths
