import hashlib
import base64
import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st


DB_PATH = os.getenv("RSVP_DB_PATH", "rsvp.db")
ADMIN_PASSWORD = os.getenv("RSVP_ADMIN_PASSWORD", "festa2026")

st.set_page_config(
    page_title="Confirmação de presença",
    page_icon="🎉",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def apply_invitation_theme():
    image_path = "convite.png"
    if not os.path.exists(image_path):
        return
    with open(image_path, "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode()
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: linear-gradient(rgba(255, 240, 248, 0.88), rgba(255, 240, 248, 0.88)),
                              url('data:image/png;base64,{encoded_image}');
            background-size: cover;
            background-position: center top;
            background-attachment: fixed;
        }}
        .block-container {{
            max-width: 760px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }}
        [data-testid="stForm"], [data-testid="stMetric"], .stAlert {{
            background: transparent;
            border-radius: 16px;
            padding: 0.8rem;
        }}
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input {{
            background: rgba(255, 255, 255, 0.72);
        }}
        h1, h2, h3 {{ color: #5b3b82; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rsvps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                attending INTEGER NOT NULL,
                adults INTEGER NOT NULL DEFAULT 0,
                children INTEGER NOT NULL DEFAULT 0,
                babies INTEGER NOT NULL DEFAULT 0,
                child_ages TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )


def save_rsvp(name, phone, attending, adults, children, babies, ages, notes):
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO rsvps
              (name, phone, attending, adults, children, babies, child_ages, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), phone.strip(), int(attending), adults, children, babies,
                ", ".join(map(str, ages)), notes.strip(), datetime.now().isoformat(timespec="seconds")
            ),
        )


def load_rsvps():
    with connection() as conn:
        return pd.read_sql_query("SELECT * FROM rsvps ORDER BY id DESC", conn)


def child_age_rows(df):
    rows = []
    for _, rsvp in df[df["attending"] == 1].iterrows():
        ages = [x.strip() for x in str(rsvp["child_ages"]).split(",") if x.strip()]
        for age in ages:
            rows.append({"Responsável": rsvp["name"], "Idade": int(age)})
    return pd.DataFrame(rows)


def count_control(label, key, default=0, min_value=0, max_value=30):
    left, center, right = st.columns([1, 3, 1])
    with center:
        return st.number_input(
            label, min_value=min_value, max_value=max_value, value=default,
            step=1, key=key, help="Use os botões + e - no celular."
        )


def guest_form():
    st.title("🎉 Confirmação de presença")
    st.write("Olá! Estamos organizando nossa festa e precisamos confirmar sua presença.")

    with st.form("rsvp_form"):
        st.subheader("1. Quem está respondendo?")
        name = st.text_input("Nome do responsável *", placeholder="Digite seu nome")
        phone = st.text_input("Telefone *", placeholder="(00) 00000-0000")

        st.subheader("2. Você irá à festa?")
        attending_label = st.radio(
            "Selecione uma opção", ["Sim, vou participar", "Não poderei participar"],
            horizontal=False
        )
        attending = attending_label.startswith("Sim")

        adults = children = babies = 0
        ages = []
        notes = ""

        if attending:
            st.subheader("3. Quantas pessoas irão?")
            adults = count_control("Adultos (10 anos ou mais)", "adults", 1)
            babies = count_control("Crianças de 7 a 9 anos", "babies", 0)
            children = count_control("Crianças até 6 anos", "children", 0)

            st.subheader("4. Mensagem para Flavia")
            notes = st.text_area(
                "Gostaria de deixar uma mensagem para Flavia?",
                placeholder="Escreva sua mensagem (opcional)", max_chars=500
            )

            st.subheader("5. Confirmação")
            total = adults + children + babies
            st.info(f"Resumo: **{adults} adulto(s), {babies} criança(s) de 7 a 9 anos, {children} criança(s) até 6 anos** — **Total: {total} pessoa(s)**")

        submitted = st.form_submit_button("🟢 CONFIRMAR PRESENÇA", use_container_width=True)

    if submitted:
        if not name.strip() or not phone.strip():
            st.error("Preencha o nome e o telefone para continuar.")
        elif attending and adults + children + babies == 0:
            st.error("Informe pelo menos uma pessoa participando.")
        else:
            save_rsvp(name, phone, attending, adults, children, babies, ages, notes)
            st.success("Presença registrada com sucesso! Obrigado.")
            st.balloons()


def admin_panel():
    st.title("📊 Painel da festa")
    if not st.session_state.get("admin_ok"):
        password = st.text_input("Senha do organizador", type="password")
        if st.button("Entrar", use_container_width=True):
            if hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest():
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Senha incorreta.")
        st.caption("A senha padrão é definida pela variável RSVP_ADMIN_PASSWORD.")
        return

    df = load_rsvps()
    confirmed = df[df["attending"] == 1]
    not_attending = df[df["attending"] == 0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Respostas recebidas", len(df))
    col2.metric("Participarão", len(confirmed))
    col3.metric("Não participarão", len(not_attending))
    col4.metric("Total de pessoas", int(confirmed[["adults", "children", "babies"]].sum().sum()) if len(confirmed) else 0)

    st.subheader("Participantes confirmados")
    col1, col2, col3 = st.columns(3)
    col1.metric("Adultos (10 anos ou mais)", int(confirmed["adults"].sum()) if len(confirmed) else 0)
    col2.metric("Crianças de 7 a 9 anos", int(confirmed["babies"].sum()) if len(confirmed) else 0)
    col3.metric("Crianças até 6 anos", int(confirmed["children"].sum()) if len(confirmed) else 0)

    if df.empty:
        st.info("Ainda não há confirmações.")
        return
    display = df.copy()
    display["Status"] = display["attending"].map({1: "Vai participar", 0: "Não poderá participar"})
    display["Total"] = display["adults"] + display["children"] + display["babies"]
    display = display.rename(columns={"name": "Responsável", "phone": "Telefone", "adults": "Adultos (10 anos ou mais)", "children": "Crianças até 6 anos", "babies": "Crianças de 7 a 9 anos", "child_ages": "Idades", "notes": "Mensagem"})
    columns = ["Responsável", "Telefone", "Adultos (10 anos ou mais)", "Crianças de 7 a 9 anos", "Crianças até 6 anos", "Total", "Mensagem"]

    st.subheader("Confirmados — informações completas")
    confirmed_display = display[display["Status"] == "Vai participar"]
    st.dataframe(confirmed_display[columns], use_container_width=True, hide_index=True)

    st.download_button("⬇️ Baixar lista em CSV", display.to_csv(index=False).encode("utf-8-sig"), "confirmacoes_festa.csv", "text/csv", use_container_width=True)


init_db()
apply_invitation_theme()
is_admin = st.query_params.get("admin", "") == "1"
if is_admin:
    admin_panel()
else:
    guest_form()
    st.divider()
    st.caption("Organizador: abra o mesmo link acrescentando **?admin=1** para acessar o painel.")
