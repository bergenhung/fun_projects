import sys

if sys.version_info < (3, 10):
    raise RuntimeError(
        f"This project needs Python 3.10 or newer (3.12 recommended); you're running {sys.version.split()[0]}. "
        "On macOS the built-in python3 is often 3.9: install a newer one from python.org or with "
        "`brew install python@3.12`, then recreate the virtual environment with it."
    )
