import sys

from thor_viewer.backend.radiometric_jpeg import load_radiometric_jpeg


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/read_radiometric_jpeg.py <IR.jpg>")
        raise SystemExit(1)

    image = load_radiometric_jpeg(sys.argv[1])

    valid = image.temperature[
        (image.temperature > -40) & (image.temperature < 600)
    ]

    print("shape:", image.temperature.shape)
    print("valid min:", float(valid.min()))
    print("valid max:", float(valid.max()))
    print("valid mean:", float(valid.mean()))
    print("center:", image.temperature_at_thermal_xy(128, 96))
    print("preview center:", image.temperature_at_preview_xy(320, 240))

    temp_range = image.metadata.get("tempRange", {})
    if temp_range:
        print("metadata low:", temp_range.get("lowTemp") / 100)
        print("metadata high:", temp_range.get("highTemp") / 100)


if __name__ == "__main__":
    main()
