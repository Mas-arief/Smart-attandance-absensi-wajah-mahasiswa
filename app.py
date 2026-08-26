"""
app.py — Sistem Absensi Wajah Mahasiswa (Flask + MySQL + YOLOv8)

Role:
  - admin     : kelola mahasiswa, lihat rekap real-time, export
  - mahasiswa : absen real-time via webcam, lihat riwayat sendiri
"""
import os
import io
import csv
import shutil
from functools import wraps
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                   session, Response, jsonify, flash, send_file)
from werkzeug.utils import secure_filename

import database
import face_engine

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ganti-kunci-ini-di-produksi")
TRAIN_DIR = "Train"
os.makedirs(TRAIN_DIR, exist_ok=True)

# Siapkan admin default (aman kalau DB belum siap: cukup diperingatkan).
try:
    database.ensure_default_admin()
except Exception as e:
    print("!! Tidak bisa menyiapkan admin default (cek koneksi MySQL):", e)


# ------------------------------------------------------------- dekorator
def login_required(role=None):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            if role and session["user"]["role"] != role:
                flash("Kamu tidak punya akses ke halaman itu.", "error")
                return redirect(url_for("home"))
            return fn(*args, **kwargs)
        return inner
    return wrapper


# ------------------------------------------------------------------ auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.verify_login(username, password)
        if user:
            session["user"] = {"username": user["username"],
                               "role": user["role"],
                               "nim": user.get("nim")}
            return redirect(url_for("home"))
        flash("Username atau password salah.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    face_engine.release_cam()
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    if session["user"]["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("mahasiswa_history"))


# --------------------------------------------------------- real-time cam
@app.route("/scan")
@login_required()
def scan():
    """Halaman scanner langsung (admin & mahasiswa)."""
    return render_template("scan.html")


@app.route("/video")
@login_required()
def video():
    return Response(face_engine.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
@login_required()
def api_status():
    """Wajah terakhir yang dikenali (untuk chip status di halaman scan)."""
    return jsonify(face_engine.last_recognized)


@app.route("/api/attendance/today")
@login_required()
def api_attendance_today():
    rows = database.attendance_by_date()
    for r in rows:
        r["tanggal"] = str(r["tanggal"])
        r["waktu"] = str(r["waktu"])
    return jsonify(rows)


# ----------------------------------------------------------------- ADMIN
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    stats = database.counts_for_dashboard()
    return render_template("admin_dashboard.html", stats=stats)


@app.route("/admin/mahasiswa")
@login_required("admin")
def admin_students():
    return render_template("admin_students.html",
                           mahasiswa=database.list_mahasiswa())


@app.route("/admin/mahasiswa/tambah", methods=["GET", "POST"])
@login_required("admin")
def admin_add_student():
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        nim = request.form.get("nim", "").strip()
        files = [f for f in request.files.getlist("foto") if f and f.filename]
        if not (nama and nim and files):
            flash("Nama, NIM, dan minimal satu foto wajib diisi.", "error")
            return redirect(url_for("admin_add_student"))

        # 1 folder per NIM, boleh diisi beberapa foto (depan, miring kiri/kanan)
        # supaya pengenalan tetap kebaca saat wajah tidak lurus ke kamera.
        folder = os.path.join(TRAIN_DIR, secure_filename(nim))
        os.makedirs(folder, exist_ok=True)

        saved_paths = []
        for i, file in enumerate(files, start=1):
            ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
            path = os.path.join(folder, f"{i}.{ext}")
            file.save(path)
            saved_paths.append(path)

        added = 0
        for path in saved_paths:
            try:
                face_engine.add_known_face(path, nim, nama)   # cek wajah + encoding
                added += 1
            except ValueError:
                pass   # foto ini wajahnya tidak kedeteksi -- lewati, foto lain tetap dipakai

        if added == 0:
            shutil.rmtree(folder, ignore_errors=True)
            flash("Wajah tidak terdeteksi pada foto manapun yang diunggah.", "error")
            return redirect(url_for("admin_add_student"))

        try:
            database.add_mahasiswa(nim, nama, f"{added} foto")   # simpan ke DB + buat akun
            flash(f"Mahasiswa {nama} ({nim}) ditambahkan ({added}/{len(files)} foto terpakai). "
                  f"Login: {nim} / {nim}", "ok")
            return redirect(url_for("admin_students"))
        except Exception as e:
            shutil.rmtree(folder, ignore_errors=True)
            face_engine.load_known_faces()   # buang encoding yang telanjur masuk memori
            flash(f"Gagal menambah mahasiswa: {e}", "error")
            return redirect(url_for("admin_add_student"))
    return render_template("admin_add_student.html")


@app.route("/admin/mahasiswa/<nim>/foto", methods=["GET", "POST"])
@login_required("admin")
def admin_add_photo(nim):
    """Tambah foto sudut wajah lain ke mahasiswa yang sudah terdaftar,
    tanpa hapus data & riwayat absensinya."""
    mhs = database.get_mahasiswa(nim)
    if not mhs:
        flash("Mahasiswa tidak ditemukan.", "error")
        return redirect(url_for("admin_students"))

    if request.method == "POST":
        files = [f for f in request.files.getlist("foto") if f and f.filename]
        if not files:
            flash("Pilih minimal satu foto.", "error")
            return redirect(url_for("admin_add_photo", nim=nim))

        folder = os.path.join(TRAIN_DIR, secure_filename(nim))
        os.makedirs(folder, exist_ok=True)
        existing = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        next_i = len(existing) + 1

        added = 0
        for i, file in enumerate(files, start=next_i):
            ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
            path = os.path.join(folder, f"{i}.{ext}")
            file.save(path)
            try:
                face_engine.add_known_face(path, nim, mhs["nama"])
                added += 1
            except ValueError:
                pass   # foto ini wajahnya tidak kedeteksi -- tetap disimpan, dilewati saat encoding

        total = len([f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))])
        database.update_foto_count(nim, total)
        flash(f"{added}/{len(files)} foto baru ditambahkan untuk {mhs['nama']}.", "ok")
        return redirect(url_for("admin_students"))

    return render_template("admin_add_photo.html", mhs=mhs)


@app.route("/admin/mahasiswa/hapus/<nim>", methods=["POST"])
@login_required("admin")
def admin_delete_student(nim):
    database.delete_mahasiswa(nim)
    folder = os.path.join(TRAIN_DIR, secure_filename(nim))
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    face_engine.load_known_faces()   # muat ulang memori encoding
    flash("Mahasiswa dihapus.", "ok")
    return redirect(url_for("admin_students"))


@app.route("/admin/rekap")
@login_required("admin")
def admin_attendance():
    return render_template("admin_attendance.html",
                           today=datetime.now().strftime("%A, %d %B %Y"))


# ---------------------------------------------------------------- export
def _fetch_export_rows(scope):
    return database.attendance_by_date() if scope == "today" else database.attendance_all()


@app.route("/admin/export/csv")
@login_required("admin")
def export_csv():
    rows = _fetch_export_rows(request.args.get("scope", "all"))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["NIM", "Nama", "Tanggal", "Waktu"])
    for r in rows:
        w.writerow([r["nim"], r["nama"], r["tanggal"], r["waktu"]])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True,
                     download_name="rekap_absensi.csv")


@app.route("/admin/export/xlsx")
@login_required("admin")
def export_xlsx():
    from openpyxl import Workbook
    rows = _fetch_export_rows(request.args.get("scope", "all"))
    wb = Workbook()
    ws = wb.active
    ws.title = "Absensi"
    ws.append(["NIM", "Nama", "Tanggal", "Waktu"])
    for r in rows:
        ws.append([r["nim"], r["nama"], str(r["tanggal"]), str(r["waktu"])])
    data = io.BytesIO()
    wb.save(data)
    data.seek(0)
    return send_file(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="rekap_absensi.xlsx")


# ------------------------------------------------------------ MAHASISWA
@app.route("/mahasiswa/riwayat")
@login_required("mahasiswa")
def mahasiswa_history():
    nim = session["user"]["nim"]
    return render_template("mahasiswa_history.html",
                           data=database.attendance_for(nim),
                           mhs=database.get_mahasiswa(nim))


if __name__ == "__main__":
    # threaded=True wajib: /video adalah stream MJPEG yang looping terus-menerus,
    # tanpa ini server dev jadi single-threaded dan request lain (mis. polling
    # /api/status tiap 1.5 detik di scan.html) macet selama kamera nyala.
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
