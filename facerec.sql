-- =====================================================================
-- facerec.sql  —  Skema database Sistem Absensi Wajah (MySQL)
-- Jalankan sekali:  mysql -u root -p < facerec.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS facerec
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE facerec;

-- Data mahasiswa ------------------------------------------------------
CREATE TABLE IF NOT EXISTS mahasiswa (
    nim         VARCHAR(30)  PRIMARY KEY,
    nama        VARCHAR(100) NOT NULL,
    foto        VARCHAR(255),               -- ringkasan tampilan (mis. "3 foto"); file aslinya ada di Train/<nim>/
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Akun login (admin & mahasiswa) -------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    username  VARCHAR(50) UNIQUE NOT NULL,
    password  VARCHAR(255) NOT NULL,        -- disimpan sebagai hash
    role      ENUM('admin','mahasiswa') NOT NULL,
    nim       VARCHAR(30),                  -- diisi hanya untuk role mahasiswa
    CONSTRAINT fk_user_mhs FOREIGN KEY (nim)
        REFERENCES mahasiswa(nim) ON DELETE CASCADE
);

-- Catatan kehadiran --------------------------------------------------
-- UNIQUE (nim, tanggal) => 1 mahasiswa hanya bisa absen 1x per hari
CREATE TABLE IF NOT EXISTS attendance (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    nim         VARCHAR(30)  NOT NULL,
    nama        VARCHAR(100) NOT NULL,
    tanggal     DATE NOT NULL,
    waktu       TIME NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_absen (nim, tanggal),
    CONSTRAINT fk_absen_mhs FOREIGN KEY (nim)
        REFERENCES mahasiswa(nim) ON DELETE CASCADE
);

-- Akun admin default dibuat otomatis oleh aplikasi saat pertama jalan
-- (username: admin, password: admin123). Ganti setelah login pertama.
