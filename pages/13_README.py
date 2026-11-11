from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.streamlit_pages import configure_page, render_project_markdown  # noqa: E402

configure_page("README")
render_project_markdown(ROOT / "README.md")
