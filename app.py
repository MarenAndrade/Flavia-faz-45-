import hashlib
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
            st.caption("Adultos: 13 anos ou mais · Crianças: 2 a 12 anos · Bebês: 0 a 1 ano")
            adults = count_control("Adultos (13 anos ou mais)", "adults", 1)
            children = count_control("Crianças (2 a 12 anos)", "children", 0)
            babies = count_control("Bebês (0 a 1 ano)", "babies", 0)

            if children:
                st.subheader("4. Idade das crianças")
                for i in range(children):
                    ages.append(st.number_input(
                        f"Criança {i + 1} — idade", min_value=2, max_value=12,
                        value=5, step=1, key=f"child_age_{i}"
                    ))

            st.subheader("5. Mensagem para Flávia")
            notes = st.text_area(
                "Gostaria de deixar uma mensagem para Flávia?",
                placeholder="Escreva sua mensagem (opcional)", max_chars=500
            )

            st.subheader("6. Confirmação")
            total = adults + children + babies
            st.info(f"Resumo: **{adults} adulto(s), {children} criança(s), {babies} bebê(s)** — **Total: {total} pessoa(s)**")

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
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Confirmações", len(confirmed))
    col2.metric("Adultos", int(confirmed["adults"].sum()) if len(confirmed) else 0)
    col3.metric("Crianças", int(confirmed["children"].sum()) if len(confirmed) else 0)
    col4.metric("Bebês", int(confirmed["babies"].sum()) if len(confirmed) else 0)
    st.metric("Total de pessoas", int(confirmed[["adults", "children", "babies"]].sum().sum()) if len(confirmed) else 0)

    st.subheader("Faixa etária das crianças")
    ages_df = child_age_rows(df)
    bands = {"0–1 ano": 0, "2–5 anos": 0, "6–9 anos": 0, "10–12 anos": 0}
    if not ages_df.empty:
        for age in ages_df["Idade"]:
            if age <= 1: bands["0–1 ano"] += 1
            elif age <= 5: bands["2–5 anos"] += 1
            elif age <= 9: bands["6–9 anos"] += 1
            else: bands["10–12 anos"] += 1
    st.dataframe(pd.DataFrame([bands]), use_container_width=True, hide_index=True)

    st.subheader("Respostas recebidas")
    if df.empty:
        st.info("Ainda não há confirmações.")
        return
    display = df.copy()
    display["Status"] = display["attending"].map({1: "Vai participar", 0: "Não poderá participar"})
    display["Total"] = display["adults"] + display["children"] + display["babies"]
    display = display.rename(columns={"name": "Responsável", "phone": "Telefone", "adults": "Adultos", "children": "Crianças", "babies": "Bebês", "child_ages": "Idades", "notes": "Mensagem"})
    st.dataframe(display[["Responsável", "Telefone", "Status", "Adultos", "Crianças", "Bebês", "Total", "Idades", "Mensagem"]], use_container_width=True, hide_index=True)
    st.download_button("⬇️ Baixar lista em CSV", display.to_csv(index=False).encode("utf-8-sig"), "confirmacoes_festa.csv", "text/csv", use_container_width=True)


init_db()
is_admin = st.query_params.get("admin", "") == "1"
if is_admin:
    admin_panel()
else:
    guest_form()
    st.divider()
    st.caption("Organizador: abra o mesmo link acrescentando **?admin=1** para acessar o painel.")
