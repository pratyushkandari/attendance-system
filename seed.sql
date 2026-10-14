-- ==============================================================================
-- Attendance System - Database Schema & Initial Seed Fixture
-- Idempotent initialization script for PostgreSQL 16 / Docker entrypoint
-- ==============================================================================

-- 1. Administrators Table
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    email VARCHAR(120) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);

-- 2. Students Table
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    roll VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    department VARCHAR(100),
    year VARCHAR(20),
    email VARCHAR(120) UNIQUE,
    embedding TEXT
);

-- 3. Attendance Ledger Table
CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    roll VARCHAR(50) NOT NULL,
    method VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for high-throughput query optimization
CREATE INDEX IF NOT EXISTS idx_admins_email ON admins(email);
CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll);
CREATE INDEX IF NOT EXISTS idx_students_email ON students(email);
CREATE INDEX IF NOT EXISTS idx_students_department ON students(department);
CREATE INDEX IF NOT EXISTS idx_attendance_roll ON attendance(roll);
CREATE INDEX IF NOT EXISTS idx_attendance_timestamp ON attendance(timestamp);

-- Seed Default System Administrator (Credentials: admin@institution.edu / AdminSecure@2026!)
INSERT INTO admins (email, password)
VALUES ('admin@institution.edu', 'scrypt:32768:8:1$jBHNXEJ0dkMR0iFU$959e25745c4f3ddc5f731e667f7e16a6dc99b9dd5c20dce0b514a14fe5580bd29a60bfc5785f487018b0705e5bf0849f934dfed9c75e21027e82ba8edeee4137')
ON CONFLICT (email) DO NOTHING;

-- Seed Sample Academic Profiles
INSERT INTO students (roll, first_name, last_name, department, year, email)
VALUES
('2024CSE001', 'John', 'Doe', 'CSE', '2024', 'john.doe@institution.edu'),
('2024ECE001', 'Jane', 'Smith', 'ECE', '2024', 'jane.smith@institution.edu')
ON CONFLICT (roll) DO NOTHING;