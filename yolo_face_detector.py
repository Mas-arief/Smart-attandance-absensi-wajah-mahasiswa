"""
yolo_face_detector.py
----------------------
Modul deteksi wajah berbasis YOLOv8 untuk sistem absensi mahasiswa.

Tujuannya: MENGGANTIKAN bagian DETEKSI wajah (face_recognition.face_locations)
dengan YOLOv8 yang lebih cepat & lebih tahan terhadap:
  - banyak wajah sekaligus (satu kelas),
  - wajah agak miring / menyamping,
  - pencahayaan kurang bagus.

Yang TIDAK diganti: proses PENGENALAN (siapa mahasiswanya) tetap memakai
library face_recognition (face_encodings + compare_faces).

Alur kerja:
    YOLOv8  ->  cari KOTAK wajah  ->  face_recognition  ->  cocokkan identitas
"""

from ultralytics import YOLO


class YoloFaceDetector:
    def __init__(self, model_path="yolov8n-face.pt", conf=0.4, min_face=24, device=None):
        """
        model_path : path bobot model wajah YOLOv8 (.pt)
        conf       : ambang keyakinan (0-1). Naikkan kalau banyak salah deteksi,
                     turunkan kalau wajah jauh sering terlewat.
        min_face   : abaikan kotak wajah yang sisinya lebih kecil dari nilai ini (piksel).
        device     : None = auto (pakai GPU kalau ada), atau "cpu" untuk paksa CPU.
        """
        self.model = YOLO(model_path)
        self.conf = conf
        self.min_face = min_face
        self.device = device

    def detect(self, image):
        """
        image : numpy array frame dari OpenCV (format BGR biasa, hasil cam.read()).

        Return: list lokasi wajah dalam format yang DIBUTUHKAN face_recognition,
                yaitu (top, right, bottom, left) untuk tiap wajah.
        """
        results = self.model.predict(
            image,
            conf=self.conf,
            device=self.device,
            verbose=False,
        )

        h, w = image.shape[:2]
        locations = []

        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes.xyxy.cpu().numpy():
                x1, y1, x2, y2 = box[:4]

                # YOLO -> (left, top, right, bottom); ubah ke format face_recognition
                left, top, right, bottom = int(x1), int(y1), int(x2), int(y2)

                # jaga agar tidak keluar dari batas gambar
                top = max(0, top)
                left = max(0, left)
                right = min(w, right)
                bottom = min(h, bottom)

                # buang kotak yang terlalu kecil (biasanya noise / wajah super jauh)
                if (right - left) < self.min_face or (bottom - top) < self.min_face:
                    continue

                # face_recognition minta urutan: (top, right, bottom, left)
                locations.append((top, right, bottom, left))

        return locations
