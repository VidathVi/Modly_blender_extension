"""
Setup script to create a Python virtual environment and install requirements.
Called as a subprocess by process_manager.py to avoid freezing Blender.
"""
import os
import subprocess
import sys
import venv
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    if len(sys.argv) < 2:
        print("Usage: setup_venv.py <api_path>")
        sys.exit(1)

    api_path = Path(sys.argv[1]).resolve()
    venv_dir = api_path / ".venv"
    req_file = api_path / "requirements.txt"

    logging.info(f"Creating virtual environment at {venv_dir}...")
    
    try:
        # Create virtual environment with pip
        venv.create(venv_dir, with_pip=True)
        logging.info("Virtual environment created successfully.")
    except Exception as e:
        logging.error(f"Failed to create virtual environment: {e}")
        sys.exit(1)

    # Determine pip executable path
    if sys.platform == "win32":
        pip_exe = venv_dir / "Scripts" / "pip.exe"
    else:
        pip_exe = venv_dir / "bin" / "pip"

    if not pip_exe.exists():
        logging.error(f"pip executable not found at {pip_exe}")
        sys.exit(1)

    if req_file.exists():
        logging.info(f"Installing dependencies from {req_file}...")
        try:
            # Upgrade pip just in case
            subprocess.run([str(pip_exe), "install", "--upgrade", "pip"], check=False)
            # Install requirements
            subprocess.run(
                [str(pip_exe), "install", "-r", str(req_file)],
                check=True,
                cwd=str(api_path)
            )
            logging.info("Dependencies installed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to install dependencies: {e}")
            sys.exit(1)
    else:
        logging.warning(f"requirements.txt not found at {req_file}. Skipping dependency installation.")

    logging.info("Setup complete.")

if __name__ == "__main__":
    main()
