import streamlit as st
import pandas as pd
from datetime import datetime
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
import mimetypes
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from airtable import Airtable

# --- API DE AIRTABLE ---
# Airtable credentials
AIRTABLE_API_KEY = st.secrets["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = st.secrets["AIRTABLE_BASE_ID"]
airtable = Airtable(AIRTABLE_BASE_ID, 'analista', AIRTABLE_API_KEY)

# --- APIs DE GOOGLE ---
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']

def autenticar_gmail():
    """Autentica y devuelve el servicio de la API de Gmail usando st.secrets."""
    creds = None
    try:
        # Usar el flujo de aplicación web con secrets de Streamlit
        flow = InstalledAppFlow.from_client_config(
            st.secrets["google_credentials"], SCOPES_GMAIL)
        creds = flow.run_local_server(port=0)
    except Exception as e:
        st.error(f"Error de autenticación con Gmail: {e}")
        st.stop()
    
    service = build('gmail', 'v1', credentials=creds)
    return service

def autenticar_drive():
    """Autentica y devuelve el servicio de la API de Google Drive usando st.secrets."""
    creds = None
    try:
        # Usar el flujo de aplicación web con secrets de Streamlit
        flow = InstalledAppFlow.from_client_config(
            st.secrets["google_credentials"], SCOPES_DRIVE)
        creds = flow.run_local_server(port=0)
    except Exception as e:
        st.error(f"Error de autenticación con Drive: {e}")
        st.stop()

    service = build('drive', 'v3', credentials=creds)
    return service

def crear_mensaje(remitente, destinatario, asunto, cuerpo_html, adjuntos=None):
    """Crea y devuelve un mensaje de correo electrónico con adjuntos."""
    mensaje = MIMEMultipart()
    mensaje['to'] = destinatario
    mensaje['from'] = remitente
    mensaje['subject'] = asunto
    
    # Cuerpo del correo
    mensaje.attach(MIMEText(cuerpo_html, 'html'))
    
    # Adjuntos
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
    """Envía el mensaje a través del servicio de la API de Gmail."""
    try:
        mensaje_enviado = (servicio.users().messages().send(userId=remitente, body=mensaje).execute())
        st.success(f"Correo enviado correctamente. ID del mensaje: {mensaje_enviado['id']}")
        return mensaje_enviado
    except Exception as e:
        st.error(f"Ocurrió un error al enviar el correo: {e}")
        return None

def generar_pdf_certificado(nombre_archivo, nombre_completo, codigo_confirmacion, nombre_analista):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    c.drawString(100, 750, f"Certificado de Entrega de Imágenes")
    c.drawString(100, 700, f"Nombre completo del analista: {nombre_analista}")
    c.drawString(100, 650, f"Nombre del cliente: {nombre_completo}")
    c.drawString(100, 600, f"Código de confirmación: {codigo_confirmacion}")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def envia_mail(mail_value, nombre_completo, codigo, files_dict, nombre_analista):
    try:
        service_gmail = autenticar_gmail()
        remitente = 'me'  # La cuenta que estás autenticando
        asunto = 'Confirmación de entrega de imágenes'
        
        cuerpo = f"""
        <html>
        <head></head>
        <body>
            <p>Hola {nombre_completo},</p>
            <p>El código para terminar el proceso es: <b>{codigo}</b></p>
            <p>Se adjunta un certificado de la entrega.</p>
        </body>
        </html>
        """
        
        # Generar el PDF
        pdf_content = generar_pdf_certificado("certificado.pdf", nombre_completo, codigo, nombre_analista)
        adjuntos = [{'nombre': 'certificado.pdf', 'contenido': pdf_content}]
        
        mensaje = crear_mensaje(remitente, mail_value, asunto, cuerpo, adjuntos)
        enviar_mensaje(service_gmail, remitente, mensaje)
        return True
    except Exception as e:
        st.error(f"No se pudo enviar el correo: {e}")
        return False

# --- UI DE STREAMLIT ---
st.title('Herramienta de Análisis')

nombre_analista = st.text_input("Nombre completo del analista:")
nombre_completo = st.text_input("Nombre completo del cliente:")
mail_value = st.text_input("Email del cliente:")

uploaded_files = st.file_uploader("Sube imágenes del cliente", type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)

if st.button("Enviar"):
    if not nombre_analista or not nombre_completo or not mail_value or not uploaded_files:
        st.error("Por favor, completa todos los campos y sube al menos un archivo.")
    else:
        # Lógica para procesar los archivos, subir a Drive, registrar en Airtable, etc.
        # ...
        
        # Generar código de confirmación
        codigo = f'CONF-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        
        # Enviar correo
        if envia_mail(mail_value, nombre_completo, codigo, {}, nombre_analista):
            st.success("Proceso completado. El correo de confirmación ha sido enviado.")
