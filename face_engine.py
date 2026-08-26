"""
face_engine.py — mesin pengenalan wajah real-time.

- Deteksi wajah : YOLOv8 (yolo_face_detector.py)
- Pengenalan    : face_recognition (encoding + compare)
- Menandai absen: database.mark_attendance()

Semua di-load MALAS (lazy): model & encoding baru dimuat saat kamera pertama
kali dipakai, supaya halaman login tetap ringan.
"""
import os
import threading
import time
import cv2
import numpy as np
import face_recognition

import database
from yolo_face_detector import YoloFaceDetector

TRAIN_DIR = "Train"
MODEL_PATH = os.environ.get("YOLO_MODEL", "yolov8n-face.pt")
CAM_INDEX = int(os.environ.get("CAM_INDEX", "0"))
TOLERANCE = 0.5           # makin kecil makin ketat
SCALE = 0.5               # pengecilan frame untuk kecepatan
CAM_WIDTH = 640           # batasi resolusi capture -- default webcam bisa 1280x720+
CAM_HEIGHT = 480          # dan itu memperlambat resize/deteksi/encode tiap frame
DETECT_EVERY = 3          # jalankan YOLO + face_recognition tiap N frame (CPU-only = lambat);
                           # frame di antaranya tetap dikirim pakai kotak terakhir supaya video mulus
JPEG_QUALITY = 80         # sedikit turunkan kualitas biar imencode lebih cepat

# state global
_detector = None
_cam = None
_lock = threading.Lock()
known_encodings = []
known_nims = []
known_names = []
last_recognized = {"nama": None, "nim": None, "baru": False}
_last_marked_at = {}          # nim -> timestamp terakhir kena mark_attendance
MARK_COOLDOWN = 5             # detik, hindari buka koneksi DB tiap frame


# ----------------------------------------------------------- inisialisasi
def _ensure_detector():
    global _detector
    if _detector is None:
        _detector = YoloFaceDetector(model_path=MODEL_PATH, conf=0.4, min_face=24)
    return _detector


def load_known_faces():
    """Baca semua foto di folder Train/ (format nama_nim.ext) lalu hitung encoding."""
    known_encodings.clear()
    known_nims.clear()
    known_names.clear()
    if not os.path.isdir(TRAIN_DIR):
        return
    for fname in os.listdir(TRAIN_DIR):
        if fname.startswith("."):
            continue
        path = os.path.join(TRAIN_DIR, fname)
        img = cv2.imread(path)
        if img is None:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        encs = face_recognition.face_encodings(rgb)
        if not encs:
            print(f"!! Wajah tidak terdeteksi di {fname}, dilewati.")
            continue
        base = fname.rsplit(".", 1)[0]        # buang ekstensi
        nama, _, nim = base.partition("_")     # nama_nim
        known_encodings.append(encs[0])
        known_names.append(nama)
        known_nims.append(nim)
    print(f">> {len(known_encodings)} wajah mahasiswa dimuat.")


def add_known_face(file_path, nim, nama):
    """Tambah satu wajah baru ke memori (dipanggil admin saat daftar mahasiswa)."""
    img = cv2.imread(file_path)
    if img is None:
        raise ValueError("File gambar tidak terbaca.")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encs = face_recognition.face_encodings(rgb)
    if not encs:
        raise ValueError("Wajah tidak terdeteksi pada foto.")
    known_encodings.append(encs[0])
    known_names.append(nama)
    known_nims.append(nim)


# --------------------------------------------------------------- kamera
def _get_cam():
    global _cam
    if _cam is None or not _cam.isOpened():
        _cam = cv2.VideoCapture(CAM_INDEX)
        _cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        _cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    return _cam


def release_cam():
    global _cam
    if _cam is not None:
        _cam.release()
        _cam = None


def generate_frames():
    """Generator MJPEG: deteksi + kenali + tandai absen, kirim frame ke browser."""
    if not known_encodings:
        load_known_faces()
    detector = _ensure_detector()
    cam = _get_cam()
    up = int(1 / SCALE)
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

    fail_streak = 0
    frame_no = 0
    boxes = []   # cache kotak+label dari deteksi terakhir, dipakai ulang di frame yang di-skip
    while True:
        with _lock:
            success, img = cam.read()
        if not success:
            fail_streak += 1
            if fail_streak > 30:   # kamera benar-benar putus, bukan cuma frame nyendat
                break
            continue
        fail_streak = 0

        try:
            frame_no += 1
            if frame_no % DETECT_EVERY == 0:
                imgS = cv2.resize(img, (0, 0), None, SCALE, SCALE)
                imgS_rgb = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)

                faces = detector.detect(imgS)                          # YOLOv8
                encodings = face_recognition.face_encodings(imgS_rgb, faces)

                boxes = []
                for enc, loc in zip(encodings, faces):
                    name, nim = "TIDAK DIKENAL", None
                    color = (0, 0, 255)                                 # merah default
                    if known_encodings:
                        dist = face_recognition.face_distance(known_encodings, enc)
                        best = int(np.argmin(dist))
                        if dist[best] <= TOLERANCE:
                            name = known_names[best].upper()
                            nim = known_nims[best]
                            color = (166, 181, 15)[::-1]                # teal (BGR)
                            now = time.monotonic()
                            if now - _last_marked_at.get(nim, 0) >= MARK_COOLDOWN:
                                _last_marked_at[nim] = now
                                baru = database.mark_attendance(nim, name)
                                last_recognized.update({"nama": name, "nim": nim, "baru": baru})
                            else:
                                last_recognized.update({"nama": name, "nim": nim, "baru": False})

                    y1, x2, y2, x1 = [v * up for v in loc]
                    boxes.append(((x1, y1, x2, y2), color, f"{name}" + (f"  {nim}" if nim else "")))

            for (x1, y1, x2, y2), color, label in boxes:
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                cv2.rectangle(img, (x1, y2 - 34), (x2, y2), color, cv2.FILLED)
                cv2.putText(img, label, (x1 + 6, y2 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            ok, buffer = cv2.imencode(".jpg", img, encode_params)
            if not ok:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + bytearray(buffer) + b"\r\n")
        except Exception as e:
            # Frame tunggal gagal diproses (mis. koneksi DB nyendat sesaat) --
            # lewati frame ini saja, JANGAN putuskan seluruh stream.
            print("Error stream (frame dilewati):", e)
            continue

    release_cam()
