# -*- coding: utf-8 -*-
"""
Created on Fri Aug  8 16:20:10 2025

@author: dsanm
"""

import os
import base64
from email.mime.text import MIMEText
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import streamlit as st
import pandas as pd
from airtable import Airtable
import random
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# ---------- CONFIGURACIÓN ----------
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']

# ---------- AUTENTICACIÓN ----------
def autenticar_gmail():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials_web.json', SCOPES_GMAIL)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)

def autenticar_drive():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials_web.json', SCOPES_DRIVE)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

# ---------- MAIL ----------
def crear_mensaje(remitente, destinatario, asunto, mensaje_texto):
    mensaje = MIMEText(mensaje_texto)
    mensaje['to'] = destinatario
    mensaje['from'] = remitente
    mensaje['subject'] = asunto
    raw_message = base64.urlsafe_b64encode(mensaje.as_bytes()).decode('utf-8')
    return {'raw': raw_message}

def enviar_mensaje(servicio, usuario_id, mensaje):
    try:
        enviado = servicio.users().messages().send(userId=usuario_id, body=mensaje).execute()
        print(f"Mensaje enviado. ID: {enviado['id']}")
    except Exception as error:
        print(f"Ocurrió un error: {error}")
        raise

def envia_mail(mail_value, codigo):
    servicio = autenticar_gmail()
    asunto = 'Confirmación de entrega de imágenes'
    mensaje_texto = f'El código para terminar el proceso es {codigo}'
    mensaje_gmail = crear_mensaje('me', mail_value, asunto, mensaje_texto)
    enviar_mensaje(servicio, 'me', mensaje_gmail)

# ---------- PDF / DRIVE ----------
def crear_pdf(selected_row):
    file_path = f"reporte_{selected_row.get('ID-partido', 'sin_id')}.pdf"
    c = canvas.Canvas(file_path, pagesize=letter)
    c.drawString(100, 750, "Reporte de Confirmación de Entrega")
    c.drawString(100, 730, "-" * 50)
    y_position = 710
    for key, value in selected_row.items():
        if key != 'Rec':
            c.drawString(100, y_position, f"{key}: {value}")
            y_position -= 20
    c.save()
    return file_path

def subir_a_drive(file_path, folder_id):
    servicio_drive = autenticar_drive()
    file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    try:
        archivo = servicio_drive.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"Archivo subido a Google Drive. ID: {archivo.get('id')}")
        return True
    except Exception as e:
        print(f"Error al subir el archivo a Google Drive: {e}")
        return False

def listar_archivos_en_drive(folder_id):
    servicio_drive = autenticar_drive()
    try:
        results = servicio_drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            pageSize=10,
            fields="files(id, name)"
        ).execute()
        items = results.get('files', [])
        if not items:
            st.info("No se encontraron archivos en la carpeta.")
        else:
            for item in items:
                st.write(f"- {item['name']} (ID: {item['id']})")
    except Exception as e:
        st.error(f"Error al listar archivos: {e}")

# ---------- STREAMLIT ----------
st.set_page_config(page_title="Dashboard de Entregas", page_icon="✅", layout="wide")
st.title("✅ Dashboard de Confirmaciones de Entrega")

@st.cache_data(ttl=600)
def conectar_a_airtable():
    at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
    result_at_Table1 = at_Table1.get('vuelos_programados_dia', view='Grid view')
    airtable_rows = [r['fields'] for r in result_at_Table1['records']]
    df = pd.DataFrame(airtable_rows)
    return df

tabla_entregas = conectar_a_airtable()

# --- Mostrar pantalla de introducción de código si ya se actualizó ---
if st.session_state.get("registro_actualizado"):
    st.subheader("Introduce el código enviado al analista")
    codigo_ingresado = st.text_input("Código")
    if codigo_ingresado:
        st.success(f"Código ingresado: {codigo_ingresado}")
    st.stop()

# --- Pantalla principal ---
if not tabla_entregas.empty:
    partidos = tabla_entregas['ID-partido'].unique().tolist()
    opcion_seleccionada = st.selectbox('Selecciona un ID de partido', options=partidos)
    df_filtrado = tabla_entregas[tabla_entregas['ID-partido'] == opcion_seleccionada]

    if not df_filtrado.empty:
        selected_row = df_filtrado.iloc[0]
        with st.form("update_form"):
            analista_value = selected_row.get('Analista', '')
            sin_analista = False
            if pd.isna(analista_value) or not analista_value:
                sin_analista = True
                analista_value = st.text_input("Analista (Manual)", value="", placeholder="Analista")
            else:
                st.text_input("Analista (Airtable)", value=analista_value, disabled=True)

            st.text_input("Piloto", value=selected_row.get('Piloto', 'N/A'), disabled=True)
            st.text_input("Fecha Partido", value=selected_row.get('Fecha partido', 'N/A'), disabled=True)

            mail_value = selected_row.get('Mail', '')
            sin_mail = False
            if pd.isna(mail_value) or not mail_value:
                sin_mail = True
                mail_value = st.text_input("Mail (Manual)", value="", placeholder="Introduce el correo...")
            else:
                st.text_input("Mail (Airtable)", value=mail_value, disabled=True)

            verificado = st.checkbox("Marcar como Verificado")
            submitted = st.form_submit_button("Actualizar Registro")

        if submitted:
            if verificado:
                random_code = random.randint(100000, 999999)

                # Crear PDF y subir
                pdf_file_path = crear_pdf(selected_row)
                drive_folder_id = "1yNFgOvRclge1SY9QtvnD980f3-4In_hs"
                if subir_a_drive(pdf_file_path, drive_folder_id):
                    os.remove(pdf_file_path)

                # Actualizar Airtable
                at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                record_id = selected_row.get('Rec')
                if record_id:
                    if sin_analista and sin_mail:
                        fields_to_update = {'Verificado': 'Pendiente', 'Analista': analista_value, 'Mail': mail_value}
                    elif sin_mail:
                        fields_to_update = {'Verificado': 'Pendiente', 'Mail': mail_value}
                    else:
                        fields_to_update = {'Verificado': 'Pendiente'}

                    at_Table1.update('vuelos_programados_dia', record_id, fields_to_update)

                    # Debug info
                    st.write("DEBUG → Enviando correo a:", mail_value)
                    st.write("DEBUG → Código generado:", random_code)

                    # Validar correo
                    if not mail_value or pd.isna(mail_value):
                        st.error("No hay correo válido para enviar el código.")
                    else:
                        try:
                            envia_mail(mail_value, random_code)
                            st.success(f"Correo enviado a {mail_value}")

                            # Guardar estado
                            st.session_state["registro_actualizado"] = True
                            st.session_state["codigo_generado"] = random_code

                            st.rerun()
                        except Exception as e:
                            st.error(f"No se pudo enviar el correo: {e}")
                else:
                    st.error("No se pudo obtener el ID del registro.")
            else:
                st.warning("Debes marcar 'Marcar como Verificado'.")
    else:
        st.warning("No se encontraron registros para el partido seleccionado.")
else:
    st.warning("No se encontraron datos en la tabla.")

# --- Archivos en Drive ---
st.subheader("Archivos en la carpeta de Google Drive")
if st.button("Listar archivos de la carpeta de Drive"):
    listar_archivos_en_drive("1yNFgOvRclge1SY9QtvnD980f3-4In_hs")
