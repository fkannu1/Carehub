# CareHub 🩺

A simple Django web app for managing Patients and Physicians.

## Features
- **Patients:** sign up, record health details (height, weight, blood pressure, sugar, etc.)
- **Physicians:** view, search, and manage linked patients.
- **Connect codes:** securely link patients to their physician.

## Quick start
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
