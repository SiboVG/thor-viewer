from __future__ import annotations

import argparse
import plistlib
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


APP_NAME = "Thor Viewer"
APP_SLUG = "thor-viewer"
BUNDLE_IDENTIFIER = "be.sibovangool.thorviewer"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_ENTRY = ROOT / "src" / "thor_viewer" / "app.py"
SVG_ICON = ROOT / "src" / "thor_viewer" / "assets" / "app-icon.svg"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
GENERATED_DIR = BUILD_DIR / "generated"
PYPROJECT = ROOT / "pyproject.toml"
LINUX_ICON_NAME = APP_SLUG


def project_version() -> str:
    try:
        return package_version("thor-viewer")
    except PackageNotFoundError:
        pass

    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')

    return "0.0.0"


def render_svg(svg_path: Path, output_path: Path, size: int) -> None:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG icon: {svg_path}")

    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(0)

    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output_path)):
        raise RuntimeError(f"Could not write icon image: {output_path}")


def build_macos_icns() -> Path:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        raise RuntimeError("macOS iconutil was not found; cannot build .icns icon")

    iconset = GENERATED_DIR / "ThorViewer.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    sizes = (16, 32, 64, 128, 256, 512, 1024)
    for size in sizes:
        if size <= 512:
            render_svg(SVG_ICON, iconset / f"icon_{size}x{size}.png", size)

        if size >= 32:
            base_size = size // 2
            render_svg(SVG_ICON, iconset / f"icon_{base_size}x{base_size}@2x.png", size)

    icns_path = GENERATED_DIR / "ThorViewer.icns"
    subprocess.run(
        [iconutil, "-c", "icns", str(iconset), "-o", str(icns_path)],
        check=True,
        cwd=ROOT,
    )
    return icns_path


def build_windows_ico() -> Path:
    from PIL import Image

    icon_dir = GENERATED_DIR / "windows-icon"
    if icon_dir.exists():
        shutil.rmtree(icon_dir)
    icon_dir.mkdir(parents=True)

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = []
    for size in sizes:
        png_path = icon_dir / f"icon_{size}x{size}.png"
        render_svg(SVG_ICON, png_path, size)
        images.append(Image.open(png_path).convert("RGBA"))

    ico_path = GENERATED_DIR / "ThorViewer.ico"
    images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(image.width, image.height) for image in images],
        append_images=images[:-1],
    )
    return ico_path


def build_linux_desktop_assets() -> tuple[Path, Path]:
    icon_root = GENERATED_DIR / "linux-icons" / "hicolor"
    if icon_root.exists():
        shutil.rmtree(icon_root)

    for size in (16, 32, 48, 64, 128, 256, 512):
        render_svg(
            SVG_ICON,
            icon_root / f"{size}x{size}" / "apps" / f"{LINUX_ICON_NAME}.png",
            size,
        )

    desktop_file = GENERATED_DIR / f"{APP_SLUG}.desktop"
    desktop_file.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_NAME}",
                "Comment=ThermalMaster Thor viewer and analysis tool",
                f"Exec={APP_NAME}/{APP_NAME}",
                f"Icon={LINUX_ICON_NAME}",
                "Terminal=false",
                "Categories=Utility;Photography;",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return desktop_file, icon_root


def pyinstaller_command(clean: bool) -> list[str]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        APP_NAME,
        "--specpath",
        str(GENERATED_DIR),
        "--collect-data",
        "thor_viewer",
    ]

    if clean:
        command.append("--clean")

    system = platform.system()
    if system == "Darwin":
        command.extend(
            [
                "--osx-bundle-identifier",
                BUNDLE_IDENTIFIER,
                "--icon",
                str(build_macos_icns()),
            ]
        )
    elif system == "Windows":
        command.extend(["--icon", str(build_windows_ico())])
    else:
        command.extend(["--icon", str(SVG_ICON)])

    command.append(str(SOURCE_ENTRY))
    return command


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x86_64")
    if system == "darwin":
        system = "macos"
    return f"{system}-{machine}"


def app_output_path() -> Path:
    if platform.system() == "Darwin":
        return DIST_DIR / f"{APP_NAME}.app"
    return DIST_DIR / APP_NAME


def update_macos_bundle_metadata() -> None:
    app_path = app_output_path()
    info_plist = app_path / "Contents" / "Info.plist"
    version = project_version()

    with info_plist.open("rb") as file:
        metadata = plistlib.load(file)

    metadata["CFBundleShortVersionString"] = version
    metadata["CFBundleVersion"] = version

    with info_plist.open("wb") as file:
        plistlib.dump(metadata, file)

    codesign = shutil.which("codesign")
    if codesign is not None:
        subprocess.run(
            [codesign, "--force", "--deep", "--sign", "-", str(app_path)],
            check=True,
            cwd=ROOT,
        )


def install_linux_desktop_assets() -> None:
    desktop_file, icon_root = build_linux_desktop_assets()
    shutil.copy2(desktop_file, DIST_DIR / desktop_file.name)

    target_icon_root = DIST_DIR / "share" / "icons" / "hicolor"
    if target_icon_root.exists():
        shutil.rmtree(target_icon_root)
    shutil.copytree(icon_root, target_icon_root)


def archive_name() -> str:
    return f"ThorViewer-{project_version()}-{platform_tag()}"


def zip_path(path: Path, output_path: Path) -> None:
    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in path.rglob("*"):
            archive.write(item, item.relative_to(path.parent))


def make_archive() -> Path:
    output_path = app_output_path()
    name = archive_name()

    if platform.system() == "Linux":
        archive_path = DIST_DIR / f"{name}.tar.gz"
        if archive_path.exists():
            archive_path.unlink()

        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(output_path, arcname=output_path.name)
            desktop_file = DIST_DIR / f"{APP_SLUG}.desktop"
            if desktop_file.exists():
                archive.add(desktop_file, arcname=desktop_file.name)
            icon_dir = DIST_DIR / "share"
            if icon_dir.exists():
                archive.add(icon_dir, arcname="share")
        return archive_path

    archive_path = DIST_DIR / f"{name}.zip"
    zip_path(output_path, archive_path)
    return archive_path


def postprocess_build(create_archive: bool) -> None:
    system = platform.system()
    if system == "Darwin":
        update_macos_bundle_metadata()
    elif system == "Linux":
        install_linux_desktop_assets()

    print(f"Built {app_output_path()}")

    if create_archive:
        print(f"Packaged {make_archive()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Thor Viewer desktop app.")
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Reuse PyInstaller build caches instead of forcing a clean build.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip creating a zip or tar.gz archive after the PyInstaller build.",
    )
    args = parser.parse_args()

    command = pyinstaller_command(clean=not args.no_clean)
    subprocess.run(command, check=True, cwd=ROOT)
    postprocess_build(create_archive=not args.no_archive)


if __name__ == "__main__":
    main()
