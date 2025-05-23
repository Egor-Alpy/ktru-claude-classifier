# /main.py
import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the app from the app module
from app.main import app

# This makes the app available for Uvicorn