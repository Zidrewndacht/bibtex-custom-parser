#!/bin/bash
# Tested in Crostini (Chromebook Linux container) and native Ubuntu 24 LTS
# Requires exsiting Python installation
# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment"
        read -p "Press any key to continue..." -n1 -s
        exit 1
    fi
    
    echo "Installing requirements..."
    ./.venv/bin/python3 -m pip install --upgrade pip
    ./.venv/bin/python3 -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Failed to install requirements"
        read -p "Press any key to continue..." -n1 -s
        exit 1
    fi
else
    echo "Virtual environment already exists"
fi

# Activate the virtual environment and run the script
echo "Activating virtual environment and running browse_db.py..."
source ./.venv/bin/activate
./.venv/bin/python3 browse_db.py

read -p "Press any key to continue..." -n1 -s