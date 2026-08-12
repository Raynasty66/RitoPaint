"""
Pixel <-> ground-plane (y=0) conversion for the League world.

Axes: y is camera height, z runs top/bottom of the screen, x runs left/right.
"""
import math

# Observer-camera defaults, read off telemetry.
OBSERVER_CAMERA_HEIGHT = 1911.85
OBSERVER_PITCH_DEG = 56.0
LEAGUE_VFOV_DEG = 40.0


class GroundPlaneProjector:
    def __init__(self, camera_height=OBSERVER_CAMERA_HEIGHT, theta_deg=OBSERVER_PITCH_DEG,
                 vfov_deg=LEAGUE_VFOV_DEG, pixel_width=3840, pixel_height=2400):
        self.camera_height = camera_height
        self.render_width = pixel_width
        self.render_height = pixel_height

        theta = math.radians(theta_deg)
        self.sin_theta = math.sin(theta)
        self.cos_theta = math.cos(theta)

        self.half_height = math.tan(math.radians(vfov_deg / 2))
        self.aspect_ratio = pixel_width / pixel_height
        self.half_width = self.aspect_ratio * self.half_height

        self.camera_x = 0.0
        self.camera_z = 0.0

    def update_camera_position(self, camera_x: float, camera_z: float):
        self.camera_x = camera_x
        self.camera_z = camera_z

    def pixel_to_ground(self, pixel_x: int, pixel_y: int) -> tuple[float, float]:
        """Screen pixel -> ground (x, z). Pixel (0, 0) is the bottom left."""
        normalized_horizontally, normalized_vertically = self._normalize_screen_coordinates(pixel_x, pixel_y)
        ray_tilt = self._ray_tilt(normalized_vertically)
        depth = self._depth_along_sightline(ray_tilt)
        return (self.camera_x + self._x_offset(depth, normalized_horizontally),
                self.camera_z + self._z_offset(depth, ray_tilt))

    def ground_to_pixel(self, ground_x: float, ground_z: float) -> tuple[float, float] | None:
        """
        Ground (x, z) -> the pixel it projects to from where the camera is now.

        None only when the point is behind the camera, the one case where a
        stroke genuinely has to break. Points merely off the edge return their
        out-of-range pixel, so a stroke leaving the screen stays connected -
        Qt clips it at the window edge.
        """
        x_offset = ground_x - self.camera_x
        z_offset = ground_z - self.camera_z

        depth = self._depth_from_z_offset(z_offset)
        if depth <= 0:
            return None

        view_offset = self._view_offset_from_z_offset(z_offset)
        return (self._pixel_column(x_offset / (self.half_width * depth)),
                self._pixel_row(view_offset / (self.half_height * depth)))

    def _normalize_screen_coordinates(self, pixel_x: int, pixel_y: int) -> tuple[float, float]:
        """Pixel coordinates onto a -1..1 scale both ways."""
        normalized_horizontally = (pixel_x / (self.render_width / 2)) - 1
        # flipped: screen rows count downwards, this axis counts upwards
        normalized_vertically = -((pixel_y / (self.render_height / 2)) - 1)
        return (normalized_horizontally, normalized_vertically)

    def _ray_tilt(self, normalized_vertically: float) -> float:
        """Tilt of the camera-to-ground ray away from the sightline: 0 at screen centre."""
        return normalized_vertically * self.half_height

    def _depth_along_sightline(self, ray_tilt: float) -> float:
        return self.camera_height / (self.sin_theta - (ray_tilt * self.cos_theta))

    def _z_offset(self, depth: float, ray_tilt: float) -> float:
        return depth * (self.cos_theta + ray_tilt * self.sin_theta)

    def _x_offset(self, depth: float, normalized_horizontally: float) -> float:
        return normalized_horizontally * depth * self.half_width

    def _depth_from_z_offset(self, z_offset: float) -> float:
        return (self.camera_height * self.sin_theta) + (z_offset * self.cos_theta)

    def _view_offset_from_z_offset(self, z_offset: float) -> float:
        """How far above (+) or below (-) the sightline the ground point sits."""
        return (z_offset * self.sin_theta) - (self.camera_height * self.cos_theta)

    def _pixel_column(self, normalized_horizontally: float) -> float:
        return (normalized_horizontally + 1) * (self.render_width / 2)

    def _pixel_row(self, normalized_vertically: float) -> float:
        return (1 - normalized_vertically) * (self.render_height / 2)
