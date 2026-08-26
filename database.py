"""
database.py — lapisan akses MySQL untuk sistem absensi.

Konfigurasi lewat environment variable (atau ubah default di bawah):
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
"""
import os
from datetime import datetime
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "user":     os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "facerec"),
}


def get_conn():
    """Buka koneksi MySQL baru."""
    return mysql.connector.connect(**DB_CONFIG)


# ---------------------------------------------------------------- setup
def ensure_default_admin():
    """Buat akun admin default kalau belum ada admin sama sekali."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    (count,) = cur.fetchone()
    if count == 0:
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, 'admin')",
            ("admin", generate_password_hash("admin123")),
        )
        conn.commit()
        print(">> Akun admin default dibuat  ->  username: admin  |  password: admin123")
    cur.close()
    conn.close()


# ----------------------------------------------------------------- auth
def get_user(username):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def verify_login(username, password):
    """Kembalikan dict user kalau valid, selain itu None."""
    user = get_user(username)
    if user and check_password_hash(user["password"], password):
        return user
    return None


# ------------------------------------------------------------ mahasiswa
def add_mahasiswa(nim, nama, foto, default_password=None):
    """
    Simpan mahasiswa + buat akun loginnya sekaligus.
    Username = NIM. Password default = NIM (bisa diubah lewat argumen).
    """
    if default_password is None:
        default_password = nim
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO mahasiswa (nim, nama, foto) VALUES (%s, %s, %s)",
        (nim, nama, foto),
    )
    cur.execute(
        "INSERT INTO users (username, password, role, nim) "
        "VALUES (%s, %s, 'mahasiswa', %s)",
        (nim, generate_password_hash(default_password), nim),
    )
    conn.commit()
    cur.close()
    conn.close()


def list_mahasiswa():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT nim, nama, foto, created_at FROM mahasiswa ORDER BY nama")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_mahasiswa(nim):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM mahasiswa WHERE nim=%s", (nim,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def delete_mahasiswa(nim):
    """Hapus mahasiswa (akun & absensinya ikut terhapus via CASCADE).
    Kembalikan nama file foto agar bisa dihapus dari folder Train/."""
    m = get_mahasiswa(nim)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM mahasiswa WHERE nim=%s", (nim,))
    conn.commit()
    cur.close()
    conn.close()
    return m["foto"] if m else None


# ------------------------------------------------------------ kehadiran
def mark_attendance(nim, nama):
    """Catat kehadiran hari ini. Aman dipanggil berkali-kali (INSERT IGNORE)."""
    now = datetime.now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT IGNORE INTO attendance (nim, nama, tanggal, waktu) "
        "VALUES (%s, %s, %s, %s)",
        (nim, nama, now.date(), now.strftime("%H:%M:%S")),
    )
    inserted = cur.rowcount > 0   # True kalau baris baru benar-benar ditambah
    conn.commit()
    cur.close()
    conn.close()
    return inserted


def attendance_by_date(tanggal=None):
    """Semua kehadiran pada satu tanggal (default: hari ini)."""
    if tanggal is None:
        tanggal = datetime.now().date()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT nim, nama, tanggal, waktu FROM attendance "
        "WHERE tanggal=%s ORDER BY waktu DESC",
        (tanggal,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def attendance_all():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT nim, nama, tanggal, waktu FROM attendance "
        "ORDER BY tanggal DESC, waktu DESC"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def attendance_for(nim):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT nim, nama, tanggal, waktu FROM attendance "
        "WHERE nim=%s ORDER BY tanggal DESC, waktu DESC",
        (nim,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# --------------------------------------------------------------- angka
def counts_for_dashboard():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mahasiswa")
    (total_mhs,) = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM attendance WHERE tanggal=CURDATE()")
    (hadir_hari_ini,) = cur.fetchone()
    cur.close()
    conn.close()
    return {
        "total_mahasiswa": total_mhs,
        "hadir_hari_ini": hadir_hari_ini,
        "belum_hadir": max(total_mhs - hadir_hari_ini, 0),
    }
