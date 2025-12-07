#!/bin/bash

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install it."
    exit 1
fi

# Create Virtual Environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate Virtual Environment
source venv/bin/activate

# Install Dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Check if Django project exists, if not create it
if [ ! -d "graphrag_marketplace" ]; then
    echo "Creating Django project..."
    django-admin startproject graphrag_marketplace .
fi

# Run Migrations
echo "Running migrations..."
python manage.py migrate

# Create Default Admin
echo "Checking/Creating default admin..."
python manage.py init_admin

# Start Server
echo "Starting server at http://127.0.0.1:8000"
python manage.py runserver 0.0.0.0:8000
