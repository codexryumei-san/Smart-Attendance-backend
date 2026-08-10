import base64

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

import os
import requests


def decode_base64_image(image_base64: str) -> np.ndarray:
    """Decode a base64 data-URL or raw base64 string into an RGB numpy array."""
    if not image_base64:
        raise ValueError("No image data provided.")

    if not CV2_AVAILABLE:
        raise ValueError("OpenCV (cv2) is required for image decoding but is not installed.")

    # Strip base64 prefix if present (data:image/jpeg;base64, or data:image/png;base64,)
    payload = image_base64.split(",", 1)[-1]
    image_bytes = base64.b64decode(payload)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr_image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if bgr_image is None:
        raise ValueError("Unable to decode image data.")

    return cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)


def extract_face_encoding(rgb_image: np.ndarray) -> tuple[np.ndarray | None, str | None]:
    """
    Detect exactly one face using HOG and return its 128-d encoding.
    Returns (encoding, error_message).
    """
    face_locations = face_recognition.face_locations(rgb_image, model="hog")
    face_count = len(face_locations)

    if face_count == 0 or face_count > 1:
        return None, "Invalid photo. Ensure exactly one face is visible."

    encodings = face_recognition.face_encodings(rgb_image, face_locations)
    if not encodings:
        return None, "Invalid photo. Ensure exactly one face is visible."

    return encodings[0], None


def encoding_to_blob(encoding: np.ndarray) -> bytes:
    return np.asarray(encoding, dtype=np.float64).tobytes()


def check_liveness(face_location: tuple, rgb_image: np.ndarray) -> tuple[bool, str | None]:
    """
    Basic liveness check stub (FR-10).
    Verifies face shape/size to detect obvious spoofs.
    Returns (is_live, error_message).
    
    face_location: (top, right, bottom, left)
    """
    top, right, bottom, left = face_location
    face_width = right - left
    face_height = bottom - top
    
    # Check minimum face size (too small = likely poor quality or distant)
    if face_width < 50 or face_height < 50:
        return False, "Face too small for reliable recognition"
    
    # Check aspect ratio (human faces typically have aspect ratio between 0.7 and 1.3)
    aspect_ratio = face_width / face_height
    if aspect_ratio < 0.7 or aspect_ratio > 1.3:
        return False, "Invalid face shape detected"
    
    # Check if face is too large (likely camera too close or cropped photo)
    image_height, image_width = rgb_image.shape[:2]
    if face_width > image_width * 0.8 or face_height > image_height * 0.8:
        return False, "Face too large - move camera back"
    
    # Check image quality (basic variance check) - only if cv2 is available
    if CV2_AVAILABLE:
        face_region = rgb_image[top:bottom, left:right]
        if face_region.size == 0:
            return False, "Invalid face region"
        
        try:
            # Calculate variance as a simple quality metric
            gray_face = cv2.cvtColor(face_region, cv2.COLOR_RGB2GRAY)
            variance = gray_face.var()
            if variance < 100:  # Too low variance = likely blurred or uniform
                return False, "Image quality too low"
        except cv2.error:
            # If cv2 fails, skip the variance check
            pass
    
    return True, None


def blob_to_encoding(blob: bytes) -> np.ndarray:
    """Convert blob back to numpy array."""
    return np.frombuffer(blob, dtype=np.float64)
