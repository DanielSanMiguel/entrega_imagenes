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
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email import encoders
import mimetypes
from io import BytesIO
import random
import secrets # Importación para generar tokens seguros

# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML, CSS
from airtable import Airtable

# --- CONFIGURACIÓN Y CONSTANTES ---
st.set_page_config(page_title="Dashboard de Entregas", page_icon="✅", layout="wide")
st.title("✅ Dashboard de Confirmaciones de Entrega")
st.markdown('<link rel="manifest" href="/manifest.json">', unsafe_allow_html=True)

# Constantes de la aplicación
DRIVE_FOLDER_ID = "1yNFgOvRclge1SY9QtvnD980f3-4In_hs"
LOGO_PATH = "./img/logo.png"
# URL del servicio de Render para el endpoint de confirmación
RENDER_CONFIRM_URL = "https://tu-servicio-de-render.onrender.com/confirmacion" 

# --- LÓGICA DE AUTENTICACIÓN ---
def check_password():
    """Returns `True` if the user has a valid password."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    try:
        password = st.secrets["PASSWORD"]
    except KeyError:
        st.error("No se encontró la contraseña en los secretos de Streamlit. Por favor, configura st.secrets['PASSWORD'].")
        st.stop()
    
    if st.session_state.authenticated:
        return True

    st.subheader("Acceso Restringido")
    password_input = st.text_input("Introduce la contraseña para acceder:", type="password")
    
    if st.button("Acceder"):
        if password_input == password:
            st.session_state.authenticated = True
            st.success("Acceso concedido.")
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
            
    return False

if not check_password():
    st.stop()

# --- GOOGLE APIs AUTH ---
@st.cache_resource(ttl=3600)
def get_creds(scopes):
    """
    Manages Google authentication using a refresh token.
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
            st.info("Por favor, sigue los pasos para generar un token y guardarlo.")
            st.stop()
    except Exception as e:
        st.error(f"Error al cargar las credenciales: {e}")
        st.stop()
    return creds

def autenticar_gmail():
    """Authenticates and returns the Gmail API service."""
    return build('gmail', 'v1', credentials=get_creds(['https://www.googleapis.com/auth/gmail.send']))

def autenticar_drive():
    """Authenticates and returns the Google Drive API service."""
    return build('drive', 'v3', credentials=get_creds(['https://www.googleapis.com/auth/drive']))

# --- FUNCIONES AUXILIARES ---
def limpiar_caracteres(texto):
    """Elimina comillas, corchetes y paréntesis de una cadena de texto."""
    if isinstance(texto, (list, tuple)) and texto:
        texto = texto[0]
    return re.sub(r'[\"\'\[\]\(\)\{\}]', "", str(texto))

def image_to_base64(image_path):
    """Convierte una imagen local en una cadena Base64."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        st.error(f"Error: No se encontró la imagen en la ruta {image_path}")
        return None

def calcular_hash_bytes(data):
    """Calcula el hash SHA256 de un objeto en bytes."""
    return hashlib.sha256(data).hexdigest()

# --- FUNCIONES DE CREACIÓN DE PDF Y SUBIDA A DRIVE ---
# Nota: Estas funciones se mantienen aquí para ser importadas en el script de Flask.
# Aunque no se usan directamente en el script de Streamlit, son necesarias
# para el flujo de trabajo completo.
def crear_pdf_con_template_en_memoria(row, analista, codigo_unico, pdf_hash="", fecha_utc="", incluir_hash=True):
    """Genera un PDF con los datos de la entrega."""
    base64_logo = image_to_base64(LOGO_PATH)
    html_template_string = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Reporte de Confirmación de Entrega</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
            .header { text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 20px; margin-bottom: 30px; }
            .header h1 { color: #007bff; }
            .content { line-height: 1.6; }
            .field-row { margin-bottom: 10px; }
            .field-name { font-weight: bold; color: #555; }
            .field-value { margin-left: 10px; }
            .logo { width: 150px; margin-bottom: 20px; }
            .legal-annex { margin-top: 50px; font-size: 11px; color: #666; }
            .legal-annex h4 { font-size: 12px; text-align: center; color: #333; }
            .hash-section { margin-top: 15px; font-size: 10px; word-break: break-all; }
        </style>
    </head>
    <body>
        <div class="header">
            {% if base64_logo %}
                <img src="data:image/png;base64,{{ base64_logo }}" alt="Logo de la empresa" class="logo">
            {% endif %}
            <h1>Reporte de Confirmación de Entrega</h1>
        </div>
        <div class="content">
            <div class="field-row">
                <span class="field-name">ID-partido:</span>
                <span class="field-value">{{ row.get('ID-partido', 'N/A') }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Analista:</span>
                <span class="field-value">{{ analista }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Piloto:</span>
                <span class="field-value">{{ row.get('Piloto', 'N/A') }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Fecha Partido:</span>
