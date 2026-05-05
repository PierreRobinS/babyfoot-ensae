import os
import sys


# Replace USERNAME and PROJECT_DIR in the PythonAnywhere WSGI file if your
# checkout path is different. The default path assumes:
# /home/USERNAME/babyfoot-ensae
USERNAME = os.environ.get("PA_USERNAME", "USERNAME")
PROJECT_DIR = os.environ.get("PROJECT_DIR", f"/home/{USERNAME}/babyfoot-ensae")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ.setdefault("DATA_DIR", os.path.join(PROJECT_DIR, "data"))
os.environ.setdefault("UPLOAD_FOLDER", os.path.join(PROJECT_DIR, "static", "uploads"))

from app import app as application
