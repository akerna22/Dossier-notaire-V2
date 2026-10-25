#!/bin/sh
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
(sleep 2; (open http://127.0.0.1:5000 || xdg-open http://127.0.0.1:5000) >/dev/null 2>&1) &
python app.py
