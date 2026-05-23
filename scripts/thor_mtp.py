from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MtpFile:
    file_id: int
    filename: str
    size: int


class MtpDisconnectedError(RuntimeError):
    pass


_FILE_ID_RE = re.compile(r"File ID:\s+(\d+)")
_FILENAME_RE = re.compile(r"\s+Filename:\s+(.+)")
_SIZE_RE = re.compile(r"\s+File size\s+(\d+)")


def run_command(args: list[str]) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def list_files() -> list[MtpFile]:
    output = run_command(["mtp-files"])

    files: list[MtpFile] = []
    current_id: int | None = None
    current_name: str | None = None
    current_size: int | None = None

    for line in output.splitlines():
        if match := _FILE_ID_RE.search(line):
            if current_id is not None and current_name is not None and current_size is not None:
                files.append(MtpFile(current_id, current_name, current_size))

            current_id = int(match.group(1))
            current_name = None
            current_size = None

        elif match := _FILENAME_RE.search(line):
            current_name = match.group(1).strip()

        elif match := _SIZE_RE.search(line):
            current_size = int(match.group(1))

    if current_id is not None and current_name is not None and current_size is not None:
        files.append(MtpFile(current_id, current_name, current_size))

    return files


def download_file(
    file: MtpFile,
    output_dir: Path,
    skip_existing: bool = True,
    retries: int = 3,
) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / file.filename

    if skip_existing and output_path.exists() and output_path.stat().st_size == file.size:
        print(f"Skipping {file.filename} already exists")
        return output_path

    for attempt in range(1, retries + 1):
        print(
            f"Downloading {file.file_id}: {file.filename} -> {output_path} "
            f"(attempt {attempt}/{retries})"
        )

        if output_path.exists():
            output_path.unlink()

        result = subprocess.run(
            ["mtp-getfile", str(file.file_id), str(output_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        output = result.stdout or ""

        if "No devices" in output or "No Devices have been found" in output:
            raise MtpDisconnectedError(
                "Thor MTP device disappeared. Wake/power-cycle the Thor and rerun download-missing-images."
            )

        if output_path.exists():
            actual_size = output_path.stat().st_size

            if actual_size == file.size:
                return output_path

            print(
                f"Size mismatch for {file.filename}: "
                f"expected {file.size}, got {actual_size}"
            )
        else:
            print(f"File was not created: {output_path}")

        if output.strip():
            print(output.strip())

    print(f"FAILED: {file.file_id} {file.filename}")
    return None


def verify_downloads(output_dir: Path) -> None:
    files = list_files()
    image_files = [
        file
        for file in files
        if file.filename.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    missing = []
    size_mismatch = []

    for file in image_files:
        path = output_dir / file.filename

        if not path.exists():
            missing.append(file)
            continue

        if path.stat().st_size != file.size:
            size_mismatch.append((file, path.stat().st_size))

    print(f"Expected images: {len(image_files)}")
    print(f"Missing: {len(missing)}")
    print(f"Size mismatch: {len(size_mismatch)}")

    for file in missing[:20]:
        print(f"Missing: {file.file_id} {file.filename}")

    for file, actual_size in size_mismatch[:20]:
        print(
            f"Size mismatch: {file.file_id} {file.filename}: "
            f"expected {file.size}, got {actual_size}"
        )


def download_missing_images(output_dir: Path, limit: int | None = None) -> None:
    files = list_files()
    image_files = [
        file
        for file in files
        if file.filename.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    failed: list[MtpFile] = []

    try:
        downloaded_count = 0

        for index, file in enumerate(image_files, start=1):
            path = output_dir / file.filename

            if path.exists() and path.stat().st_size == file.size:
                continue

            print(f"[{index}/{len(image_files)}] ", end="")
            result = download_file(file, output_dir, skip_existing=False)

            if result is None:
                failed.append(file)
            else:
                downloaded_count += 1
                if limit is not None and downloaded_count >= limit:
                    print(f"Reached limit of {limit} downloads.")
                    break

    except MtpDisconnectedError as exc:
        print()
        print(f"Disconnected: {exc}")
        print("Progress is saved. Wake/power-cycle the Thor and rerun:")
        print(f"  uv run python scripts/thor_mtp.py download-missing-images --out {output_dir}")

    print()
    print(f"Done. Failed: {len(failed)}")

    if failed:
        failed_path = output_dir / "failed_downloads.txt"
        with failed_path.open("w", encoding="utf-8") as f:
            for file in failed:
                f.write(f"{file.file_id},{file.size},{file.filename}\n")

        print(f"Wrote failed list to {failed_path}")


def download_all_images(output_dir: Path) -> None:
    files = list_files()

    image_files = [
        file
        for file in files
        if file.filename.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    print(f"Found {len(image_files)} image files")

    for file in image_files:
        download_file(file, output_dir)


def download_latest_pair(output_dir: Path) -> None:
    files = list_files()

    ir_files = [
        file
        for file in files
        if file.filename.endswith("-IR.jpg")
    ]

    if not ir_files:
        raise RuntimeError("No IR files found")

    latest_ir = sorted(ir_files, key=lambda f: f.filename)[-1]
    base = latest_ir.filename.replace("-IR.jpg", "")

    pair = [
        file
        for file in files
        if file.filename in {f"{base}-IR.jpg", f"{base}-DC.jpg"}
    ]

    print(f"Latest capture base: {base}")

    for file in sorted(pair, key=lambda f: f.filename):
        download_file(file, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    latest = sub.add_parser("download-latest")
    latest.add_argument("--out", default="thor_downloads")

    all_images = sub.add_parser("download-all-images")
    all_images.add_argument("--out", default="thor_downloads")

    verify = sub.add_parser("verify")
    verify.add_argument("--out", default="thor_downloads")

    missing = sub.add_parser("download-missing-images")
    missing.add_argument("--out", default="thor_downloads")
    missing.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    if args.command == "list":
        for file in list_files():
            print(f"{file.file_id:5d}  {file.size:10d}  {file.filename}")

    elif args.command == "verify":
        verify_downloads(Path(args.out))

    elif args.command == "download-missing-images":
        download_missing_images(Path(args.out), limit=args.limit)

    elif args.command == "download-latest":
        download_latest_pair(Path(args.out))

    elif args.command == "download-all-images":
        download_all_images(Path(args.out))


if __name__ == "__main__":
    main()
