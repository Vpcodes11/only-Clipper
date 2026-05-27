"""
Face Processor — Dynamic face tracking with active speaker detection.
Gaussian smoothing for cinematic camera movement.
Graceful fallback if MediaPipe is not available.
"""
import logging
import os

logger = logging.getLogger(__name__)

# Resilient imports for computer vision libraries
try:
    import cv2
except ImportError:
    cv2 = None
    logger.warning("OpenCV (cv2) is not installed. Face tracking will be disabled.")

try:
    import numpy as np
except ImportError:
    np = None
    logger.warning("NumPy is not installed. Face tracking will be disabled.")

try:
    from mediapipe.python.solutions import face_detection as mp_face_detection
except ImportError:
    try:
        from mediapipe.solutions import face_detection as mp_face_detection
    except ImportError:
        mp_face_detection = None
        logger.warning("MediaPipe is not installed. Dynamic face tracking will be disabled.")


class FaceTracker:
    def __init__(self):
        self._face_detection = None

    @property
    def face_detection(self):
        if mp_face_detection is None:
            return None
        if self._face_detection is None:
            try:
                self._face_detection = mp_face_detection.FaceDetection(
                    model_selection=1,  # Full-range (within 5m)
                    min_detection_confidence=0.5
                )
            except Exception as e:
                logger.error("Failed to initialize MediaPipe FaceDetection: %s", e)
                self._face_detection = None
        return self._face_detection

    def get_dynamic_crop_coordinates(self, video_path, start_time, end_time,
                                     target_width=1080, target_height=1920):
        """
        Calculates smooth, dynamic crop coordinates using active speaker detection
        and Gaussian-weighted smoothing for cinematic camera movement.

        Returns a dict: {'crop_w', 'crop_h', 'coords': {timestamp: x_pixel}} or None.
        """
        if cv2 is None or np is None or mp_face_detection is None:
            logger.info("Face tracking dependencies missing. Dynamic crop disabled.")
            return None

        detector = self.face_detection
        if detector is None:
            logger.info("MediaPipe detector is unavailable. Dynamic crop disabled.")
            return None

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("Failed to open video file for tracking: %s", video_path)
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Crop width based on target aspect ratio
        crop_w = int(src_h * (target_width / target_height))

        # If source is already portrait or narrower than target crop, tracking is not needed
        if crop_w >= src_w:
            cap.release()
            logger.info("Video aspect ratio is narrower than or equal to target. No crop needed.")
            return None

        # Sample positions
        sample_interval = 0.2
        sample_interval = max(0.2, 1.0 / max(fps, 1))
        frame_num = int(start_time * fps)
        end_frame = int(end_time * fps)

        raw_centers = []
        timestamps = []

        while frame_num <= end_frame:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                break

            actual_pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if actual_pos > end_time + sample_interval:
                break

            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = detector.process(rgb_frame)
                center_x = self._pick_active_speaker_center(results, src_w)
                raw_centers.append(center_x)
                timestamps.append(actual_pos if actual_pos > 0 else start_time + frame_num / fps)
            except Exception as e:
                logger.debug("Error processing frame %d: %s", frame_num, e)

            frame_num += max(1, int(sample_interval * fps))

        cap.release()

        if not raw_centers:
            logger.warning("No face detections found in this time segment.")
            return None

        # Apply Gaussian Smoothing (cinematic camera momentum)
        smoothed_centers = self._gaussian_smooth(raw_centers, sigma=2.0)

        # Clamp and map back to timestamps
        coord_map = {}
        for i, center in enumerate(smoothed_centers):
            min_center = crop_w / 2
            max_center = src_w - (crop_w / 2)
            clamped = max(min_center, min(center, max_center))
            top_left_x = int(clamped - (crop_w / 2))
            coord_map[round(timestamps[i], 2)] = top_left_x

        return {
            'crop_w': crop_w,
            'crop_h': src_h,
            'coords': coord_map
        }

    def _pick_active_speaker_center(self, results, src_w) -> float:
        """
        Active speaker detection: picks face bounding box height/width ratio
        as a basic speaker detection heuristic. Falls back to frame center.
        """
        if not results or not results.detections:
            return src_w / 2

        if len(results.detections) == 1:
            bbox = results.detections[0].location_data.relative_bounding_box
            return (bbox.xmin + bbox.width / 2) * src_w

        best_score = -1
        best_center_x = src_w / 2

        for det in results.detections:
            bbox = det.location_data.relative_bounding_box
            w = max(bbox.width, 1e-5)
            h = max(bbox.height, 1e-5)
            # Heuristic: speaking is vertical-stretching (mouth open) + detection confidence
            score = det.score[0] * (h / w)
            if score > best_score:
                best_score = score
                best_center_x = (bbox.xmin + w / 2) * src_w

        return best_center_x

    @staticmethod
    def _gaussian_smooth(values: list, sigma: float = 2.0) -> list:
        """Applies 1D Gaussian kernel to smooth camera coordinates."""
        if len(values) < 3 or np is None:
            return values

        arr = np.array(values, dtype=float)
        radius = int(3 * sigma)
        x = np.arange(-radius, radius + 1)
        kernel = np.exp(-0.5 * (x / sigma) ** 2)
        kernel /= kernel.sum()

        padded = np.pad(arr, radius, mode='edge')
        smoothed = np.convolve(padded, kernel, mode='valid')
        return smoothed.tolist()

    def generate_sendcmd_file(self, tracking: dict, output_path: str) -> str:
        """
        Writes an FFmpeg sendcmd script to dynamically adjust the crop X coordinate at
        frame boundaries using linear interpolation for smooth camera panning.
        """
        lines = []
        coords = tracking['coords']
        timestamps = sorted(coords.keys())

        if not timestamps:
            return output_path

        start_t = min(timestamps)
        interp_interval = 1.0 / 30.0  # Interpolate at 30 fps
        x_values = [coords[ts] for ts in timestamps]
        rel_times = [max(0.0, ts - start_t) for ts in timestamps]

        current_t = 0.0
        seg_idx = 0

        while seg_idx < len(rel_times) - 1 and current_t <= rel_times[-1]:
            t0, x0 = rel_times[seg_idx], x_values[seg_idx]
            t1, x1 = rel_times[seg_idx + 1], x_values[seg_idx + 1]

            while current_t <= t1:
                frac = (current_t - t0) / max(t1 - t0, 1e-6)
                frac = max(0.0, min(1.0, frac))
                # Ease-in-out quad for cinematic deceleration at keypoints
                eased = frac * frac * (3.0 - 2.0 * frac)
                interp_x = int(x0 + (x1 - x0) * eased)
                lines.append(f"{current_t:.3f} [OUT] crop x {interp_x};")
                current_t += interp_interval

            seg_idx += 1

        if current_t <= rel_times[-1] + interp_interval:
            lines.append(f"{rel_times[-1]:.3f} [OUT] crop x {int(x_values[-1])};")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

        return output_path


tracker = FaceTracker()
