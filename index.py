from pathlib import Path

from streamlit.starlette import App

# Vercel entry point. Locally, use `streamlit run dashboard/app.py` instead.
app = App(Path(__file__).resolve().parent / "dashboard" / "app.py")
