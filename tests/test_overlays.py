import unittest

import numpy as np

from thor_viewer.processing.overlays import (
    draw_center_temperature_label,
    draw_temperature_gradient_bar,
    draw_temperature_point_marker,
)


class TemperatureOverlayTest(unittest.TestCase):
    def make_frame(self) -> np.ndarray:
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def test_gradient_bar_paints_left_edge_without_resizing(self) -> None:
        frame = self.make_frame()

        out = draw_temperature_gradient_bar(frame, 20.0, 35.0, copy=True)

        self.assertEqual(out.shape, frame.shape)
        # The legend lives near the left edge and must add color there.
        self.assertGreater(out[:, :40].sum(), 0)
        # The original frame is untouched when copy=True.
        self.assertEqual(frame.sum(), 0)

    def test_gradient_bar_in_place(self) -> None:
        frame = self.make_frame()

        out = draw_temperature_gradient_bar(frame, 20.0, 35.0, copy=False)

        self.assertIs(out, frame)
        self.assertGreater(frame.sum(), 0)

    def test_center_label_draws_near_top(self) -> None:
        frame = self.make_frame()

        draw_center_temperature_label(frame, 36.6, copy=False)

        self.assertGreater(frame[:40].sum(), 0)

    def test_point_marker_draws_at_position(self) -> None:
        frame = self.make_frame()

        draw_temperature_point_marker(
            frame, (320, 240), 42.0, color=(0, 0, 255), label_prefix="Max", copy=False
        )

        # Marker crosshair touches the target pixel neighborhood.
        self.assertGreater(frame[232:248, 312:328].sum(), 0)

    def test_point_marker_clamps_out_of_bounds_position(self) -> None:
        frame = self.make_frame()

        # Should not raise for a position outside the frame.
        draw_temperature_point_marker(
            frame, (5000, -10), 42.0, color=(255, 0, 0), label_prefix="Min", copy=False
        )

        self.assertEqual(frame.shape, (480, 640, 3))


if __name__ == "__main__":
    unittest.main()
