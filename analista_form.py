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
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseUpload
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
import uuid
# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML, CSS
from airtable import Airtable

# --- App configuration ---
st.set_page_config(page_title="Protocolo entrega de imágenes", page_icon="✅", layout="wide")
st.title("Protocolo de confidencialidad en la entrega de imágenes")

# --- PWA Manifest Link ---
st.markdown('<link rel="manifest" href="/manifest.json">', unsafe_allow_html=True)


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

@st.cache_resource(ttl=3600)
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

def calcular_hash_bytes(data):
    """Calcula el hash SHA256 de un objeto en bytes."""
    return hashlib.sha256(data).hexdigest()
    
# --- PDF CREATION FUNCTION (MODIFIED) ---
def crear_pdf_con_template_en_memoria(selected_row, analista_value, codigo_unico, pdf_hash="", fecha_utc="", incluir_hash=True):
    """
    Generates a report PDF in memory (BytesIO) using an HTML template and Jinja2.
    """
    logo_path = "./img/LogoFLY-FUT.png"
    base64_logo = image_to_base64(logo_path)
    
    html_template_string = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Reporte de Confirmación de Entrega</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
            .header { text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
            .header h1 { color: #333; }
            .content { line-height: 1.6; }
            .field-row { margin-bottom: 10px; }
            .field-name { font-weight: bold; color: #555; }
            .field-value { margin-left: 10px; }
            .logo { width: 300px; margin-bottom: 20px; }
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
            <h1>Confirmación de Entrega</h1>
        </div>
        <div class="content">
            <div class="field-row">
                <span class="field-name">ID-partido:</span>
                <span class="field-value">{{ row['ID-partido'] }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Analista:</span>
                <span class="field-value">{{ analista }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Piloto:</span>
                <span class="field-value">{{ row['Piloto'] }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Fecha Partido:</span>
                <span class="field-value">{{ row['Fecha partido'] }}</span>
            </div>

        </div>
        <hr>
        <div class="legal-annex">
            <p>La confirmación de su recepción constituyen una aceptación expresa de la entrega física del material
            identificado en este documento, así como la asunción de su custodia.</p>
            <p>Esta confirmación constituye una firma electrónica simple y queda asociada a la identidad
            del receptor, la fecha y hora de confirmación y la descripción del material
            entregado. El registro se conserva para fines de auditoría y resolución de disputas.</p>
            {% if incluir_hash %}
            <div class="field-row hash-section">
                <span class="field-name">Fecha/hora UTC de generación:</span>
                <span class="field-value">{{ fecha_utc }}</span>
            </div>
            <div class="field-row hash-section">
                <span class="field-name">Hash (SHA256) del PDF final:</span>
                <span class="field-value">{{ pdf_hash }}</span>
            </div>
            {% endif %}
        </div>
    </body>
    </html>
    """

    template = Template(html_template_string)
    html_out = template.render(
        row=selected_row,  
        analista=analista_value,  
        codigo=codigo_unico,  
        pdf_hash=pdf_hash,
        base64_logo=base64_logo,
        fecha_utc=fecha_utc,
        incluir_hash=incluir_hash
    )

    pdf_buffer = BytesIO()
    HTML(string=html_out).write_pdf(target=pdf_buffer)
    return pdf_buffer.getvalue()

# --- Function to upload PDF to Drive (MODIFIED) ---
def subir_a_drive_desde_bytes(pdf_bytes, file_name, folder_id):
    """
    Uploads a file to Google Drive from a bytes object, makes it public, and returns its view link.
    """
    servicio_drive = autenticar_drive()
    if not servicio_drive:
        return None

    file_metadata = {'name': file_name, 'parents': [folder_id]}

    # Usar MediaIoBaseUpload, que es la clase correcta para objetos de tipo BytesIO.
    media = MediaIoBaseUpload(BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
    
    try:
        archivo = servicio_drive.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        st.success(f"Archivo subido a Google Drive. ID: {archivo.get('id')}")

        servicio_drive.permissions().create(
            fileId=archivo.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            fields='id'
        ).execute()

        return archivo.get('webContentLink')
    except Exception as e:
        st.error(f"Error al subir o compartir el archivo: {e}")
        return None

def envia_mail(mail_value, nombre_completo_piloto, codigo, nombre_analista, partido_id, fecha_partido, tipo_evento):
    """
    Envía un correo electrónico al analista con el código único y los detalles legales.
    """
    try:
        service_gmail = autenticar_gmail()
        if not service_gmail:
            return False
            
        remitente = 'me'

        if isinstance(tipo_evento, list) and tipo_evento:
            tipo_evento_str = tipo_evento[0].capitalize()
        else:
            tipo_evento_str = str(tipo_evento).capitalize()

        asunto = f'[Fly-Fut] Confirmación de entrega de tarjeta SD - {tipo_evento_str}: {partido_id}'
        
        cuerpo_html = f"""
        <html>
        <head></head>
        <body>
            <p>Hola <b>{nombre_analista}</b>,</p>
            <p>El piloto <b>{nombre_completo_piloto}</b> ha iniciado la entrega física de la tarjeta SD con el material del **{tipo_evento_str}** <b>{partido_id}</b>, jugado el <b>{fecha_partido}</b>.</p>
            <hr style="border: 0; border-top: 1px solid #ccc; margin: 30px 0;">
            <h4>Declaración de No Repudio y Validez Legal</h4>
            <p>Al hacer clic en el siguiente enlace, usted está confirmando la recepción y aceptación de la custodia de la tarjeta SD. Esta acción genera un registro digital con fecha y hora, que certifica la entrega del material.</p>
            <p style="text-align: center; margin-top: 20px;">
                <a href="URL_DEL_ENLACE_DE_CONFIRMACION" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">Confirmar Entrega</a>
            </p>
            <p>Esta confirmación tiene carácter de <b>firma electrónica simple</b> y garantiza la integridad de la transacción, impidiendo que cualquiera de las partes pueda repudiar la entrega posteriormente. Este registro se almacena de forma segura en nuestra base de datos para futuras auditorías.</p>
            <p>Si tienes alguna pregunta o incidencia, por favor, contacta con nuestro departamento legal en <a href="mailto:legal@fly-fut.com">legal@fly-fut.com</a>.</p>
            <p>Gracias por tu colaboración.</p>
            <p>Atentamente,<br>
            El equipo de Fly-Fut</p>
        </body>
        </html>
        """
        
        mensaje = crear_mensaje(remitente, mail_value, asunto, cuerpo_html)
        enviar_mensaje(service_gmail, remitente, mensaje)
        return True
    except Exception as e:
        st.error(f"No se pudo enviar el correo: {e}")
        return False
    
def enviar_pdf_confirmacion(mail_value, nombre_piloto, nombre_analista, partido_id, adjuntos=None):
    """
    Sends the final confirmation email with the attached PDF.
    """
    try:
        service_gmail = autenticar_gmail()
        if not service_gmail:
            return False
            
        remitente = 'me'
        asunto = f'Confirmación de entrega de imágenes - PDF adjunto para {partido_id}'
        
        cuerpo_html = f"""
        <html>
        <body>
            <p>Hola {nombre_analista},</p>
            <p>Se adjunta el certificado de confirmación de entrega del material del partido <b>{partido_id}</b>, que fue validado por el piloto <b>{nombre_piloto}</b>.</p>
            <p>Este documento certifica la correcta transferencia del material según nuestro protocolo de seguridad.</p>
            <p>Gracias por tu colaboración.</p>
        </body>
        </html>
        """
        
        mensaje = crear_mensaje(remitente, mail_value, asunto, cuerpo_html, adjuntos)
        enviar_mensaje(service_gmail, remitente, mensaje)
        return True
    except Exception as e:
        st.error(f"Ocurrió un error al enviar el correo de confirmación: {e}")
        return False

# --- AIRTABLE API ---
AIRTABLE_API_KEY = st.secrets["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = st.secrets["AIRTABLE_BASE_ID"]
airtable = Airtable(AIRTABLE_BASE_ID, 'analista', AIRTABLE_API_KEY)


# --- MAIN APPLICATION CODE (AUTHENTICATED USERS ONLY) ---
def is_valid_email(email):
    """
    Validates the format of an email address using a regular expression.
    """
    regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(regex, email) is not None

@st.cache_data(ttl=600)
def conectar_a_airtable():
    at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
    result_at_Table1 = at_Table1.get('Confirmaciones_de_Entrega', view='Grid view')
    airtable_rows = [r['fields'] for r in result_at_Table1['records']]
    df = pd.DataFrame(airtable_rows)

    # Verifica si la columna 'Codigo_unico' existe y la crea si no es así
    if 'Codigo_unico' not in df.columns:
        df['Codigo_unico'] = '------'
    
    return df

tabla_entregas = conectar_a_airtable()

# --- Main screen ---
if not tabla_entregas.empty:
    partidos = tabla_entregas['ID-partido'].unique().tolist()
    opcion_seleccionada = st.selectbox('Selecciona un ID de partido', options=partidos)
    df_filtrado = tabla_entregas[tabla_entregas['ID-partido'] == opcion_seleccionada]

    if not df_filtrado.empty:
        selected_row = df_filtrado.iloc[0]
        st.session_state['selected_row'] = selected_row
        
        with st.form("update_form"):
            analista_list = selected_row.get('Analista', '')
            analista_raw = limpiar_caracteres(analista_list[0])
            analista_value_input = st.text_input("Analista", value=analista_raw)
            st.text_input("Piloto", value=selected_row.get('Piloto', 'N/A'), disabled=True)
            st.text_input("Fecha Partido", value=selected_row.get('Fecha partido', 'N/A'), disabled=True)
            mail_list = selected_row.get('Mail', '')
            mail_raw=limpiar_caracteres(mail_list[0])
            mail_value_input = st.text_input("Mail", value=mail_raw)
            
            # --- Se elimina la opción de radio, se asume que siempre es "Enviar enlace"
            
            submitted = st.form_submit_button("Enviar enlace de confirmación")

        if submitted:
            if not analista_value_input or not mail_value_input:
                st.warning("El nombre del analista y el correo son obligatorios.")
            elif not is_valid_email(mail_value_input):
                st.warning("Por favor, introduce una dirección de correo electrónico válida.")
            
            # Lógica de "Enviar enlace"
            at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
            record_id = selected_row.get('Rec')
            
            if record_id:
                # Update Airtable to 'Pendiente' before generating PDF
                # 1. Generar un token único
                token = str(uuid.uuid4())
                # 2. Actualizar Airtable con el nuevo token y el estado "Pendiente"
                fields_to_update_pending = {
                    'Analista(Form)': analista_value_input,
                    'Mail(Form)': mail_value_input,
                    'Verificado': 'Pendiente', 
                    'Codigo_unico': token
                }
                at_Table1.update('Confirmaciones_de_Entrega', record_id, fields_to_update_pending)
                st.success("Registro de Airtable actualizado a 'Pendiente'.")

                with st.spinner("Generando PDF y subiendo a Google Drive..."):
                    codigo_placeholder = "N/A"
                    fecha_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    
                    pdf_content_without_hash = crear_pdf_con_template_en_memoria(
                        selected_row,
                        analista_value_input,
                        codigo_placeholder,
                        fecha_utc=fecha_utc,
                        incluir_hash=False
                    )
                    pdf_hash = calcular_hash_bytes(pdf_content_without_hash)
                    final_pdf_content = crear_pdf_con_template_en_memoria(
                        selected_row,
                        analista_value_input,
                        codigo_placeholder,
                        pdf_hash=pdf_hash,
                        fecha_utc=fecha_utc,
                        incluir_hash=True
                    )

                    file_name = f"reporte_verificado_{selected_row.get('ID-partido', 'sin_id')}.pdf"
                    pdf_url = subir_a_drive_desde_bytes(final_pdf_content, file_name, DRIVE_FOLDER_ID)
                
                if pdf_url:
                    # Update Airtable to 'Verificado' after successful PDF upload
                    fields_to_update = {
                        'Verificado': 'Pendiente',
                        'PDF': [{'url': pdf_url}],
                        'Hash_PDF': pdf_hash,
                        'Codigo_unico': token
                    }
                    at_Table1.update('Confirmaciones_de_Entrega', record_id, fields_to_update)
                    st.success("Registro de Airtable actualizado a 'Pendiente' y el PDF subido.")
                    
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.error("No se pudo subir el PDF. Por favor, inténtalo de nuevo.")
            else:
                st.error("No se pudo obtener el ID del registro para actualizar Airtable.")
            
    else:
        st.warning("No se encontraron registros para el partido seleccionado.")
else:
    st.warning("No se encontraron datos en la tabla.")
