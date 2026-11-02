import cv2
import numpy as np
import zxingcpp

MODEL_MAX_SIDE = 1600


def _gray(image: bytes):
    return cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)


def _zxing(img) -> list[str]:
    return [b.text for b in zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode) if b.text]


def _opencv(img) -> list[str]:
    for det in (cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()):
        try:
            ok, values, _, _ = det.detectAndDecodeMulti(img)
        except cv2.error:
            continue
        if ok and any(values):
            return [v for v in values if v]
    return []


def decode_qr(image: bytes) -> list[str]:
    img = _gray(image)
    if img is None:
        return []
    attempts = [lambda: _zxing(img)]
    if max(img.shape) < 3000:
        attempts.append(lambda: _zxing(cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)))
    attempts.append(lambda: _opencv(img))
    for attempt in attempts:
        found = []
        for v in attempt():
            v = v.strip()
            if v and v not in found:
                found.append(v)
        if found:
            return found
    return []


def for_model(image: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale large photos before sending them to a model. QR decoding uses the full image."""
    img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if img is None or max(img.shape[:2]) <= MODEL_MAX_SIDE:
        return image, media_type
    scale = MODEL_MAX_SIDE / max(img.shape[:2])
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes(), "image/jpeg"


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        with open(path, "rb") as f:
            print(path, decode_qr(f.read()) or "no QR code found")
