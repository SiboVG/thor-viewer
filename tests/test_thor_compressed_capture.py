import os
import unittest
from unittest import mock

from thor_viewer.backend.thor_compressed_capture import (
    DSHOW_CAPTURE_CATEGORY_GUID,
    ThorCompressedLiveCapture,
    dshow_device_candidates,
    find_ffmpeg,
)


class DshowDeviceCandidatesTest(unittest.TestCase):
    QT_ID = (
        "\\\\?\\usb#vid_1d6b&pid_1102&mi_03#b&9913074&0&0003"
        "#{e5323777-f976-4f5b-9b55-b94699c46e44}\\global"
    )

    def test_friendly_name_comes_first(self) -> None:
        candidates = dshow_device_candidates("UVC Camera 0", self.QT_ID)

        self.assertEqual(candidates[0], "video=UVC Camera 0")
        self.assertEqual(len(candidates), 3)

    def test_pnp_candidates_rewrite_category_guid(self) -> None:
        candidates = dshow_device_candidates("UVC Camera 0", self.QT_ID)

        self.assertIn(DSHOW_CAPTURE_CATEGORY_GUID, candidates[1])
        self.assertTrue(candidates[1].startswith("video=@device_pnp_\\\\?\\"))
        self.assertIn("{e5323777-f976-4f5b-9b55-b94699c46e44}", candidates[2])

    def test_non_symbolic_link_id_yields_only_friendly_name(self) -> None:
        candidates = dshow_device_candidates("UVC Camera 0", "some-opaque-id")

        self.assertEqual(candidates, ["video=UVC Camera 0"])


class FindFfmpegTest(unittest.TestCase):
    def test_environment_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"THOR_FFMPEG": "X:/custom/ffmpeg.exe"}):
            self.assertEqual(find_ffmpeg(), "X:/custom/ffmpeg.exe")

    def test_falls_back_to_path_lookup(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("THOR_FFMPEG", None)
            with mock.patch(
                "thor_viewer.backend.thor_compressed_capture.shutil.which",
                return_value="C:/tools/ffmpeg.exe",
            ):
                self.assertEqual(find_ffmpeg(), "C:/tools/ffmpeg.exe")


class ThorCompressedLiveCaptureTest(unittest.TestCase):
    def test_open_clears_previous_error(self) -> None:
        capture = ThorCompressedLiveCapture([], 640, 480, 25)
        capture._set_error("boom")

        with mock.patch.object(ThorCompressedLiveCapture, "_capture_loop"):
            capture.open()
            try:
                self.assertIsNone(capture.error_message)
            finally:
                capture.close()

    def test_close_is_idempotent_without_open(self) -> None:
        capture = ThorCompressedLiveCapture(["video=missing"], 640, 480, 25)
        capture.close()
        capture.close()
        self.assertIsNone(capture.read_latest())
        self.assertIsNone(capture.latest_frame)


if __name__ == "__main__":
    unittest.main()
