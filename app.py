import hashlib
import base64
from io import BytesIO
import os
import sqlite3
import unicodedata
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None


DB_PATH = os.getenv("RSVP_DB_PATH", "rsvp.db")
ADMIN_PASSWORD = os.getenv("RSVP_ADMIN_PASSWORD", "festa2026")
GOOGLE_SHEET_ID = "1kbdYLlOTNsxvFeD--ExKlU69ZxdoWMJHt1jc4S7TyEY"
SHEET_HEADERS = [
    "id", "Responsável", "Telefone", "attending",
    "Adultos (10 anos ou mais)", "Crianças até 6 anos",
    "Crianças de 7 a 9 anos", "Idades", "Mensagem",
    "created_at", "Status", "Total",
]

st.set_page_config(
    page_title="Confirmação de presença",
    page_icon="🎉",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def apply_invitation_theme():
    image_path = next((path for path in ("Convite.jpeg", "convite.jpeg", "convite.png") if os.path.exists(path)), None)
    if image_path is None:
        return
    with open(image_path, "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode()
    image_mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: linear-gradient(rgba(255, 240, 248, 0.93), rgba(255, 240, 248, 0.93)),
                              url('data:{image_mime};base64,{encoded_image}');
            background-size: cover;
            background-position: center top;
            background-repeat: no-repeat;
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


def google_worksheet():
    """Returns the first worksheet when Google Sheets secrets are configured."""
    if gspread is None or Credentials is None:
        st.session_state["google_sheet_error"] = "As bibliotecas gspread/google-auth não estão instaladas."
        return None
    try:
        st.session_state.pop("google_sheet_error", None)
        service_account = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(
            service_account,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(credentials)
        return client.open_by_key(GOOGLE_SHEET_ID).sheet1
    except Exception as exc:
        st.session_state["google_sheet_error"] = f"{type(exc).__name__}: {exc}"
        return None


def using_google_sheets():
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


def google_rows_to_df(worksheet):
    """Lê a planilha sem get_all_records, aceitando cabeçalhos repetidos/vazios."""
    values = worksheet.get_all_values()
    columns = [
        "id", "name", "phone", "attending", "adults", "children", "babies",
        "child_ages", "notes", "created_at",
    ]
    if not values or not any(str(cell).strip() for cell in values[0]):
        return pd.DataFrame(columns=columns)

    def normalize(value):
        text = unicodedata.normalize("NFKD", str(value))
        text = "".join(char for char in text if not unicodedata.combining(char))
        return " ".join(text.strip().lower().split())

    header_to_field = {
        "id": "id", "responsavel": "name", "nome do responsavel": "name", "nome": "name",
        "telefone": "phone", "phone": "phone",
        "attending": "attending", "participara": "attending",
        "adultos (10 anos ou mais)": "adults", "adultos": "adults",
        "criancas ate 6 anos": "children", "criancas (ate 6 anos)": "children",
        "children": "children",
        "criancas de 7 a 9 anos": "babies", "criancas (7 a 9 anos)": "babies",
        "babies": "babies",
        "idades": "child_ages", "child ages": "child_ages",
        "mensagem": "notes", "observacoes": "notes", "notes": "notes",
        "created at": "created_at", "created_at": "created_at", "data/hora": "created_at",
        "status": "status", "total": "total",
    }

    records = []
    headers = [str(header).strip() for header in values[0]]
    for raw_row in values[1:]:
        if not any(str(cell).strip() for cell in raw_row):
            continue
        raw_cells = list(raw_row)
        # Compatibilidade com a linha que foi gravada deslocada à direita
        # pela versão anterior. Não altera a planilha; apenas lê corretamente.
        leading_empty = 0
        while leading_empty < len(raw_cells) and not str(raw_cells[leading_empty]).strip():
            leading_empty += 1
        if leading_empty and len(raw_cells) > len(headers):
            raw_cells = raw_cells[leading_empty:]
        row = raw_cells + [""] * max(0, len(headers) - len(raw_cells))
        record = {column: "" for column in columns}
        record["status"] = ""
        for header, value in zip(headers, row):
            field = header_to_field.get(normalize(header))
            if field:
                record[field] = value

        if not str(record["attending"]).strip():
            record["attending"] = record.get("status", "")
        attending_key = normalize(record["attending"])
        record["attending"] = 0 if attending_key in {
            "0", "false", "nao", "nao podera participar", "nao poderei participar"
        } else 1
        for field in ["id", "adults", "children", "babies"]:
            try:
                record[field] = int(float(str(record[field]).replace(",", ".")))
            except (TypeError, ValueError):
                record[field] = 0
        records.append({column: record[column] for column in columns})

    return pd.DataFrame(records, columns=columns)


def save_rsvp(name, phone, attending, adults, children, babies, ages, notes):
    worksheet = google_worksheet()
    if worksheet is None:
        detail = st.session_state.get("google_sheet_error", "verifique os Secrets e o compartilhamento da planilha")
        raise RuntimeError(f"Google Sheets não está conectado: {detail}")
    created_at = datetime.now().isoformat(timespec="seconds")
    existing = google_rows_to_df(worksheet)
    next_id = int(existing["id"].max()) + 1 if not existing.empty else 1
    status = "Vai participar" if attending else "Não poderá participar"
    total = adults + children + babies
    all_values = worksheet.get_all_values()
    if not all_values or not any(str(cell).strip() for cell in all_values[0]):
        worksheet.update("A1:L1", [SHEET_HEADERS], value_input_option="RAW")
        all_values = worksheet.get_all_values()
    row_to_write = [
        next_id, name.strip(), phone.strip(), int(attending), adults,
        children, babies, ", ".join(map(str, ages)), notes.strip(),
        created_at, status, total,
    ]
    # Grava explicitamente em A:L para nunca depender da detecção automática
    # de tabela do Google Sheets.
    next_row = len(all_values) + 1
    worksheet.update(
        f"A{next_row}:L{next_row}",
        [row_to_write],
        value_input_option="USER_ENTERED",
    )


def load_rsvps():
    worksheet = google_worksheet()
    if worksheet is None:
        detail = st.session_state.get("google_sheet_error", "verifique os Secrets e o compartilhamento da planilha")
        raise RuntimeError(f"Google Sheets não está conectado: {detail}")
    return google_rows_to_df(worksheet)


def child_age_rows(df):
    rows = []
    for _, rsvp in df[df["attending"] == 1].iterrows():
        ages = [x.strip() for x in str(rsvp["child_ages"]).split(",") if x.strip()]
        for age in ages:
            rows.append({"Responsável": rsvp["name"], "Idade": int(age)})
    return pd.DataFrame(rows)


def dataframe_to_excel(dataframe):
    """Gera um arquivo Excel em memória para o organizador baixar."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Confirmacoes")
    return output.getvalue()


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
    st.markdown("🤫 **É surpresa!** Contamos com a ajuda de todos para guardar esse segredo até o grande dia! E capriche no look anos 80 — venha se divertir! 💃🕺")

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
            try:
                save_rsvp(name, phone, attending, adults, children, babies, ages, notes)
            except Exception as exc:
                st.error("Não foi possível registrar a resposta no Google Sheets.")
                st.caption(f"Detalhe: {exc}")
            else:
                if attending:
                    st.success("Presença registrada com sucesso! Obrigado.")
                    st.balloons()
                else:
                    st.info("😢 Que pena! Sentiremos sua falta.")
                    st.markdown(
                        """
                        <style>
                        @keyframes sad-float {
                            0% { transform: translateY(40px); opacity: 0; }
                            25% { opacity: 1; }
                            100% { transform: translateY(-90px); opacity: 0; }
                        }
                        .sad-float {
                            text-align: center;
                            font-size: 3.5rem;
                            animation: sad-float 2.8s ease-in-out forwards;
                        }
                        </style>
                        <div class="sad-float">😢</div>
                        """,
                        unsafe_allow_html=True,
                    )


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

    try:
        df = load_rsvps()
    except Exception as exc:
        st.error("Não foi possível carregar a lista do Google Sheets.")
        st.code(str(exc))
        st.info("Nenhuma resposta foi apagada. Corrija o Secrets ou o compartilhamento da planilha e atualize o app.")
        return
    if using_google_sheets() and st.session_state.get("google_sheet_error"):
        st.error(
            "Não foi possível conectar ao Google Sheets. "
            "Confira o conteúdo de Secrets, o compartilhamento da planilha "
            "e veja o detalhe abaixo."
        )
        st.code(st.session_state["google_sheet_error"])
        st.info("As respostas exibidas abaixo podem ser apenas do armazenamento local, não da planilha.")
    elif using_google_sheets():
        st.success("Conectado ao Google Sheets")
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

    # Botão para abrir a planilha online.
    google_sheet_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit"
    st.link_button(
        "📋 Abrir lista no Google Sheets",
        google_sheet_url,
        use_container_width=True,
    )

    display = df.copy()
    display["Status"] = display["attending"].map({1: "Vai participar", 0: "Não poderá participar"})
    display["Total"] = display["adults"] + display["children"] + display["babies"]
    display = display.rename(columns={"name": "Responsável", "phone": "Telefone", "adults": "Adultos (10 anos ou mais)", "children": "Crianças até 6 anos", "babies": "Crianças de 7 a 9 anos", "child_ages": "Idades", "notes": "Mensagem"})
    columns = ["Responsável", "Telefone", "Adultos (10 anos ou mais)", "Crianças de 7 a 9 anos", "Crianças até 6 anos", "Total", "Mensagem"]

    export_columns = ["Responsável", "Telefone", "Adultos (10 anos ou mais)", "Crianças de 7 a 9 anos", "Crianças até 6 anos", "Status", "Total", "Mensagem"]
    st.download_button(
        "⬇️ Baixar lista em Excel",
        data=dataframe_to_excel(display[export_columns]),
        file_name="confirmacoes_festa.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    if df.empty:
        st.info("Ainda não há confirmações.")
        return

    st.subheader("Confirmados — informações completas")
    confirmed_display = display[display["Status"] == "Vai participar"]
    st.dataframe(confirmed_display[columns], use_container_width=True, hide_index=True)

init_db()
apply_invitation_theme()
is_admin = st.query_params.get("admin", "") == "1"
if is_admin:
    admin_panel()
else:
    guest_form()
    st.divider()
    st.caption("Organizador: abra o mesmo link acrescentando **?admin=1** para acessar o painel.")
