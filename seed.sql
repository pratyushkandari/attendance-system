-- Create Database
CREATE DATABASE attendence_db;

-- Connect to DB
\c attendence_db;

-- Students Table
CREATE TABLE students (
    id SERIAL PRIMARY KEY,
    roll VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    department VARCHAR(100),
    year VARCHAR(20),
    email VARCHAR(120) UNIQUE,
    embedding TEXT
);

-- Attendance Table
CREATE TABLE attendance (
    id SERIAL PRIMARY KEY,
    roll VARCHAR(20) NOT NULL,
    method VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sample Data
INSERT INTO students (roll, first_name, last_name, department, year, email)
VALUES
('2024CSE001', 'John', 'Doe', 'CSE', '2024', 'john@example.com'),
('2024ECE001', 'Jane', 'Smith', 'ECE', '2024', 'jane@example.com');