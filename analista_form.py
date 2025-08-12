# -*- coding: utf-8 -*-
"""
Created on Sun Aug 10 09:38:21 2025

@author: dsanm
"""

import streamlit as st
import pandas as pd
import os
import re
import hashlib
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import base64
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
from io import BytesIO
import random

# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML, CSS
from airtable import Airtable

# --- App configuration ---
st.set_page_config(page_title="Dashboard de Entregas", page_icon="✅", layout="wide")
st.title("✅ Dashboard de Confirmaciones de Entrega")

# --- LOGIN LOGIC ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

try:
    PASSWORD = st.secrets["PASSWORD"]
except KeyError:
    st.error("No se encontró la contraseña en los secretos de Streamlit. Por favor, configura st.secrets['PASSWORD'].")
    st.stop()

if not st.session_state["authenticated"]:
    st.subheader("Acceso Restringido")
    password_input = st.text_input("Introduce la contraseña para acceder:", type="password")
    
    if st.button("Acceder"):
        if password_input == PASSWORD:
            st.session_state["authenticated"] = True
            st.success("Acceso concedido.")
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    
    st.stop()

# --- GOOGLE APIs ---
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
DRIVE_FOLDER_ID = "1yNFgOvRclge1SY9QtvnD980f3-4In_hs"

def get_creds(scopes):
    """
    Manages Google authentication using a refresh token
    stored in st.secrets, to avoid the local server flow.
    """
    creds = None
    try:
        creds_info = st.secrets.get("google_creds")
        if creds_info and "token" in creds_info and "refresh_token" in creds_info:
            creds = Credentials.from_authorized_user_info(info=creds_info, scopes=scopes)

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
        else:
            st.error("No se encontraron credenciales válidas en st.secrets.")
            st.info("Por favor, sigue los pasos de la conclusión para generar un token y guardarlo.")
            st.stop()
    except Exception as e:
        st.error(f"Error al cargar las credenciales: {e}")
        st.stop()
    
    return creds

def autenticar_gmail():
    """Authenticates and returns the Gmail API service."""
    creds = get_creds(SCOPES_GMAIL)
    if creds:
        return build('gmail', 'v1', credentials=creds)
    return None

def autenticar_drive():
    """Authenticates and returns the Google Drive API service."""
    creds = get_creds(SCOPES_DRIVE)
    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

def crear_mensaje(remitente, destinatario, asunto, cuerpo_html, adjuntos=None):
    """Creates and returns an email message with attachments."""
    mensaje = MIMEMultipart()
    mensaje['to'] = destinatario
    mensaje['from'] = remitente
    mensaje['subject'] = asunto
    
    mensaje.attach(MIMEText(cuerpo_html, 'html'))
    
    if adjuntos:
        for adjunto_dict in adjuntos:
            filename = adjunto_dict['nombre']
            file_content = adjunto_dict['contenido']
            
            content_type, encoding = mimetypes.guess_type(filename)
            if content_type is None or encoding is not None:
                content_type = 'application/octet-stream'
            
            main_type, sub_type = content_type.split('/', 1)
            
            if main_type == 'image':
                msg = MIMEImage(file_content, _subtype=sub_type)
            elif main_type == 'audio':
                msg = MIMEAudio(file_content, _subtype=sub_type)
            else:
                msg = MIMEBase(main_type, sub_type)
                msg.set_payload(file_content)
                encoders.encode_base64(msg)
            
            msg.add_header('Content-Disposition', 'attachment', filename=filename)
            mensaje.attach(msg)
    
    return {'raw': base64.urlsafe_b64encode(mensaje.as_bytes()).decode()}

def enviar_mensaje(servicio, remitente, mensaje):
    """Sends the message via the Gmail API service."""
    try:
        mensaje_enviado = (servicio.users().messages().send(userId=remitente, body=mensaje).execute())
        st.success(f"Correo enviado correctamente. ID del mensaje: {mensaje_enviado['id']}")
        return mensaje_enviado
    except Exception as e:
        st.error(f"Ocurrió un error al enviar el correo: {e}")
        return None

def limpiar_caracteres(texto):
    """
    Elimina comillas (simples y dobles) y corchetes ([], (), {}) de una cadena de texto.
    """
    caracteres_a_eliminar = "[\"\'\[\]\(\)\{\}]"
    return re.sub(caracteres_a_eliminar, "", texto)

# --- Función auxiliar para convertir imagen a Base64 ---
def image_to_base64(image_path):
    """Convierte una imagen local en una cadena Base64."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        st.error(f"Error: No se encontró la imagen en la ruta {image_path}")
        return None

def calcular_hash_pdf(pdf_path):
    """Calcula el hash SHA256 de un archivo PDF."""
    try:
        with open(pdf_path, "rb") as f:
            bytes = f.read()
            readable_hash = hashlib.sha256(bytes).hexdigest()
        return readable_hash
    except FileNotFoundError:
        st.error(f"Error al calcular el hash: No se encontró el archivo en {pdf_path}")
        return None
    
# --- PDF CREATION FUNCTION ---
def crear_pdf_con_template(selected_row, analista_value, codigo_unico, pdf_hash=""):
    """
    Generates a report PDF using an HTML template and Jinja2.
    """
    logo_path = "./img/logo.png"
    base64_logo = image_to_base64(logo_path)
    
    # Renderizamos la plantilla con los datos
    if base64_logo:
        html_template_string = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Reporte de Confirmación de Entrega</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                .header {{ text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 20px; margin-bottom: 30px; }}
                .header h1 {{ color: #007bff; }}
                .content {{ line-height: 1.6; }}
                .field-row {{ margin-bottom: 10px; }}
                .field-name {{ font-weight: bold; color: #555; }}
                .field-value {{ margin-left: 10px; }}
                .logo {{ width: 150px; margin-bottom: 20px; }}
                .hash-section {{ margin-top: 50px; font-size: 10px; word-break: break-all; }}
            </style>
        </head>
        <body>
            <div class="header">
                <img src="data:image/png;base64,{base64_logo}" alt="Logo de la empresa" class="logo">
                <h1>Reporte de Confirmación de Entrega</h1>
            </div>
            <div class="content">
                <div class="field-row">
                    <span class="field-name">ID-partido:</span>
                    <span class="field-value">{{{{ row['ID-partido'] }}}}</span>
                </div>
                <div class="field-row">
                    <span class="field-name">Analista:</span>
                    <span class="field-value">{{{{ analista }}}}</span>
                </div>
                <div class="field-row">
                    <span class="field-name">Piloto:</span>
                    <span class="field-value">{{{{ row['Piloto'] }}}}</span>
                </div>
                <div class="field-row">
                    <span class="field-name">Fecha Partido:</span>
                    <span class="field-value">{{{{ row['Fecha partido'] }}}}</span>
                </div>
                <div class="field-row">
                    <span class="field-name">Código Único:</span>
                    <span class="field-value">{{{{ codigo }}}}</span>
                </div>
                <div class="field-row hash-section">
                    <span class="field-name">Hash (SHA256) del PDF final:</span>
                    <span class="field-value">{{{{ pdf_hash }}}}</span>
                </div>
            </div>
        </body>
        </html>
        """
    else:
        html_template_string = f"""
        <!DOCTYPE html>
        <html lang="es">
        ... ...
        </html>
        """

    template = Template(html_template_string)
    html_out = template.render(row=selected_row, analista=analista_value, codigo=codigo_unico, pdf_hash=pdf_hash)

    pdf_content = HTML(string=html_out).write_pdf()
    
    file_path = f"reporte_{selected_row.get('ID-partido', 'sin_id')}.pdf"
    with open(file_path, "wb") as f:
        f.write(pdf_content)

    return file_path

# --- Function to upload PDF to Drive (modified) ---
def subir_a_drive(file_path, folder_id):
