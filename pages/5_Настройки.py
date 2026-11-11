from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.registries import FLAGS, flag_state  # noqa: E402
from kp_tz_check.streamlit_pages import configure_page, render_header  # noqa: E402

configure_page("Настройки")
render_header(
    "Настройки",
    "Параметры подключения читаются из .env и не редактируются в интерфейсе.",
)

env_path = ROOT / ".env"
st.subheader("Провайдеры")
providers = [
    ("local-SLM(uStd)", "UNSLOTH_MODEL", "UNSLOTH_API_KEY"),
    ("local-SLM(oLm)", "OLLAMA_MODEL", "OLLAMA_API_KEY"),
    ("Sechenov.AI", "TOGETHER_MODEL", "TOGETHER_API_KEY"),
]
for label, model_key, secret_key in providers:
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.write(f"Модель: `{model_key}`")
        st.write(f"API key: `{secret_key}` — значение скрыто")

st.subheader("Реестры")
st.caption(
    "ЕГРЮЛ при включённом флаге читает открытую форму egrul.nalog.ru. "
    "Остальные флаги без клиента останавливают проверку и сеть не вызывают."
)
for name in FLAGS:
    state = "включён" if flag_state()[name] else "выключен"
    st.write(f"`{name}`: {state}")

st.subheader("Файл конфигурации")
st.info(f"`.env` найден: {'да' if env_path.exists() else 'нет'}")
st.caption("Для применения изменений в .env перезапустите Streamlit.")

st.subheader("Состояние текущего запуска")
if st.session_state.get("results"):
    st.write(f"Провайдер: `{st.session_state.get('last_provider', '—')}`")
    st.write(f"Комплект: `{st.session_state.get('last_run_path', '—')}`")
    st.write(f"Fingerprint: `{st.session_state.get('pack_fingerprint', '—')}`")
else:
    st.info("Проверка ещё не запускалась.")
