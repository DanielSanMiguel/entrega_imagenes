# -*- coding: utf-8 -*-
"""
Dashboard de Confirmaciones de Entrega con Streamlit
Autor: Gemini
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
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload # Importamos MediaIoBaseUpload
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
from io import BytesIO
import random

# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML
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
    st.error("Error: No se encontró la contraseña en los secretos de Streamlit. Por favor, configura st.secrets['PASSWORD'].")
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

# --- GOOGLE API UTILITIES ---
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']

def get_creds(scopes):
    """
    Manages Google authentication using a refresh token stored in st.secrets.
    """
    try:
        creds_info = st.secrets.get("google_creds")
        if not creds_info or "token" not in creds_info or "refresh_token" not in creds_info:
            st.error("No se encontraron credenciales de Google válidas en st.secrets.")
            st.info("Por favor, consulta la documentación para configurar las credenciales correctamente.")
            st.stop()
        
        creds = Credentials.from_authorized_user_info(info=creds_info, scopes=scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds
    except Exception as e:
        st.error(f"Error al cargar las credenciales: {e}")
        st.stop()

@st.cache_resource(ttl=3600)
def autenticar_gmail():
    """Authenticates and returns the Gmail API service."""
    creds = get_creds(SCOPES_GMAIL)
    return build('gmail', 'v1', credentials=creds)

@st.cache_resource(ttl=3600)
def autenticar_drive():
    """Authenticates and returns the Google Drive API service."""
    creds = get_creds(SCOPES_DRIVE)
    return build('drive', 'v3', credentials=creds)

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
            
            msg = MIMEBase(main_type, sub_type)
            msg.set_payload(file_content)
            encoders.encode_base64(msg)
            
            msg.add_header('Content-Disposition', 'attachment', filename=filename)
            mensaje.attach(msg)
    
    return {'raw': base64.urlsafe_b64encode(mensaje.as_bytes()).decode()}

def enviar_mensaje(servicio, remitente, mensaje):
    """Sends the message via the Gmail API service."""
    try:
        servicio.users().messages().send(userId=remitente, body=mensaje).execute()
        return True
    except Exception as e:
        st.error(f"Ocurrió un error al enviar el correo: {e}")
        return False

# --- AIRTABLE UTILITIES ---
@st.cache_data(ttl=600)
def conectar_a_airtable():
    """Connects to Airtable and fetches data from the 'Confirmaciones_de_Entrega' table."""
    try:
        airtable_base_id = st.secrets["AIRTABLE_BASE_ID"]
        airtable_api_key = st.secrets["AIRTABLE_API_KEY"]
        at = Airtable(airtable_base_id, airtable_api_key)
        records = at.get('Confirmaciones_de_Entrega', view='Grid view')['records']
        df = pd.DataFrame([r['fields'] for r in records])
        
        # Ensure 'Rec' column exists, which is the record ID
        if 'id' in [r for r in records][0]:
            df['Rec'] = [r['id'] for r in records]
        
        # Safely handle list fields
        for col in ['Analista', 'Mail', 'Tipo']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: x[0] if isinstance(x, list) and x else None)
        
        return df
    except Exception as e:
        st.error(f"Error al conectar con Airtable: {e}")
        return pd.DataFrame()

# --- PDF GENERATION & UPLOAD ---
def image_to_base64(image_path):
    """Converts a local image to a Base64 string."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        st.error(f"Error: No se encontró la imagen en la ruta {image_path}")
        return None

def calcular_hash_pdf(pdf_content):
    """Calcula el hash SHA256 de un archivo PDF en memoria."""
    return hashlib.sha256(pdf_content).hexdigest()

def crear_pdf_con_template(selected_row, analista_value, codigo_unico, pdf_hash, fecha_utc):
    """
    Generates a report PDF using an HTML template and Jinja2.
    """
    logo_path = "./img/logo.png"
    base64_logo = image_to_base64(logo_path)
    
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
            .legal-annex {{ margin-top: 50px; font-size: 11px; color: #666; }}
            .legal-annex h4 {{ font-size: 12px; text-align: center; color: #333; }}
            .hash-section {{ margin-top: 15px; font-size: 10px; word-break: break-all; }}
        </style>
    </head>
    <body>
        <div class="header">
            {f'<img src="data:image/png;base64,{base64_logo}" alt="Logo de la empresa" class="logo">' if base64_logo else ''}
            <h1>Reporte de Confirmación de Entrega</h1>
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
            <div class="field-row">
                <span class="field-name">Código Único:</span>
                <span class="field-value">{{ codigo }}</span>
            </div>
        </div>
        <hr>
        <div class="legal-annex">
            <h4>Anexo Legal — Declaración de Recepción y Custodia del Material</h4>
            <p>La introducción del código único proporcionado por este sistema y la confirmación de su
            recepción constituyen una aceptación expresa de la entrega física del material
            identificado en este documento, así como la asunción de su custodia.</p>
            <p>Esta confirmación constituye una firma electrónica simple y queda asociada a la identidad
            del receptor, el código único, la fecha y hora de confirmación y la descripción del material
            entregado. El registro se conserva para fines de auditoría y resolución de disputas.</p>
            <p>Fly-Fut S.L. se reserva el derecho a presentar esta documentación como prueba ante
            cualquier autoridad administrativa o judicial competente.</p>
            <div class="field-row hash-section">
                <span class="field-name">Fecha/hora UTC de generación:</span>
                <span class="field-value">{{ fecha_utc }}</span>
            </div>
            <div class="field-row hash-section">
                <span class="field-name">Hash (SHA256) del PDF final:</span>
                <span class="field-value">{{ pdf_hash }}</span>
            </div>
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
        fecha_utc=fecha_utc
    )

    pdf_content = HTML(string=html_out).write_pdf()
    return pdf_content

def subir_a_drive(pdf_content, filename, folder_id):
    """
    Uploads a file to Google Drive, makes it public, and returns its web view link.
    """
    servicio_drive = autenticar_drive()
    if not servicio_drive:
        return None

    file_metadata = {'name': filename, 'parents': [folder_id]}
    
    # Correction: Use MediaIoBaseUpload for in-memory byte streams.
    # MediaFileUpload expects a file path, not a BytesIO object.
    media = MediaIoBaseUpload(BytesIO(pdf_content), mimetype='application/pdf')

    try:
        archivo = servicio_drive.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        
        # Make file public
        servicio_drive.permissions().create(
            fileId=archivo.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            fields='id'
        ).execute()

        return archivo.get('webContentLink')
    except Exception as e:
        st.error(f"Error al subir o compartir el archivo: {e}")
        return None

def enviar_pdf_confirmacion(mail_value, nombre_piloto, nombre_analista, partido_id, adjuntos):
    """
    Sends the final confirmation email with the attached PDF.
    """
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
    return enviar_mensaje(service_gmail, remitente, mensaje)

# --- MAIN APPLICATION LOGIC ---
def show_main_dashboard(tabla_entregas):
    """Displays the main dashboard for selecting a match and updating Airtable."""
    if tabla_entregas.empty:
        st.warning("No se encontraron datos en la tabla de Airtable. Por favor, verifica la conexión.")
        return

    partidos_pendientes = tabla_entregas[tabla_entregas['Verificado'].isin(['Pendiente', None])]['ID-partido'].unique().tolist()
    
    if not partidos_pendientes:
        st.info("No hay partidos pendientes de verificación.")
        return

    opcion_seleccionada = st.selectbox('Selecciona un ID de partido', options=partidos_pendientes)
    df_filtrado = tabla_entregas[tabla_entregas['ID-partido'] == opcion_seleccionada]

    if df_filtrado.empty:
        st.warning("No se encontraron registros para el partido seleccionado.")
        return
    
    selected_row = df_filtrado.iloc[0]
    st.session_state['selected_row'] = selected_row
    
    with st.form("update_form"):
        analista_value_input = st.text_input("Analista", value=selected_row.get('Analista', ''))
        st.text_input("Piloto", value=selected_row.get('Piloto', 'N/A'), disabled=True)
        st.text_input("Fecha Partido", value=selected_row.get('Fecha partido', 'N/A'), disabled=True)
        mail_value_input = st.text_input("Mail", value=selected_row.get('Mail', ''))
        
        verificado = st.checkbox("Iniciar Proceso de Confirmación")
        submitted = st.form_submit_button("Actualizar Registro y Enviar Código")

    if submitted:
        if verificado:
            if not analista_value_input or not mail_value_input:
                st.warning("El nombre del analista y el correo son obligatorios.")
                return
            
            random_code = random.randint(100000, 999999)
            
            try:
                # Actualizar Airtable
                at_update = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                record_id = selected_row.get('Rec')
                if not record_id:
                    st.error("No se pudo obtener el ID del registro para actualizar Airtable.")
                    return
                
                fields_to_update = {
                    'Verificado': 'Pendiente',
                    'Codigo_unico': str(random_code),
                }
                # Use a specific table name for the update. Assuming 'Confirmaciones_de_Entrega'
                at_update.update('Confirmaciones_de_Entrega', record_id, fields_to_update)
                st.success("Registro de Airtable actualizado a 'Pendiente'.")

                # Enviar correo al analista
                if enviar_mensaje(
                    servicio=autenticar_gmail(),
                    remitente='me',
                    mensaje=crear_mensaje(
                        remitente='me',
                        destinatario=mail_value_input,
                        asunto=f'[Fly-Fut] Código de Confirmación - {selected_row.get("ID-partido", "sin_id")}',
                        cuerpo_html=f"""
                        <p>Hola {analista_value_input},</p>
                        <p>El piloto {selected_row.get('Piloto', '')} ha iniciado la entrega de la tarjeta SD para el partido {selected_row.get('ID-partido', 'sin_id')}.</p>
                        <p>Por favor, usa el siguiente código para validar la entrega en el dashboard:</p>
                        <h2 style="text-align: center; color: #007bff; border: 2px solid #007bff; padding: 10px;">{random_code}</h2>
                        """
                    )
                ):
                    st.success(f"Correo enviado a {mail_value_input} con el código de confirmación.")
                    
                    st.session_state["registro_actualizado"] = True
                    st.session_state["codigo_generado"] = str(random_code)
                    st.session_state["mail_value_for_pdf"] = mail_value_input
                    st.session_state["analista_value_for_pdf"] = analista_value_input
                    
                    st.rerun()
                else:
                    st.error("No se pudo enviar el correo.")
            except Exception as e:
                st.error(f"Error en el proceso de actualización: {e}")
        else:
            st.warning("Debes marcar 'Iniciar Proceso de Confirmación' para continuar.")

def show_code_input():
    """Displays the screen for entering the unique code."""
    st.subheader("Paso 2: Introduce el código enviado al analista")
    codigo_ingresado = st.text_input("Código de confirmación", key="codigo_input")
    
    if st.button("Finalizar Proceso", key="finalizar_button"):
        if codigo_ingresado == st.session_state.get("codigo_generado"):
            st.success("Código correcto. Procediendo con el envío del PDF.")
            
            try:
                selected_row = st.session_state['selected_row']
                mail_value = st.session_state.get('mail_value_for_pdf', '')
                analista_value = st.session_state.get('analista_value_for_pdf', '')
                codigo_generado = st.session_state.get("codigo_generado")
                DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]

                with st.spinner("Generando PDF y subiendo a Google Drive..."):
                    fecha_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    
                    # Generamos el PDF con un hash temporal para luego calcular el real
                    temp_pdf_content = crear_pdf_con_template(
                        selected_row, 
                        analista_value, 
                        codigo_generado, 
                        pdf_hash="[PENDIENTE]", 
                        fecha_utc=fecha_utc
                    )
                    
                    pdf_hash = calcular_hash_pdf(temp_pdf_content)
                    
                    # Regeneramos el PDF con el hash real
                    final_pdf_content = crear_pdf_con_template(
                        selected_row, 
                        analista_value, 
                        codigo_generado, 
                        pdf_hash=pdf_hash,
                        fecha_utc=fecha_utc
                    )
                    
                    filename = f"reporte_{selected_row.get('ID-partido', 'sin_id')}.pdf"
                    pdf_url = subir_a_drive(final_pdf_content, filename, DRIVE_FOLDER_ID)
                
                if pdf_url:
                    adjuntos = [{'nombre': filename, 'contenido': final_pdf_content}]
                    if enviar_pdf_confirmacion(
                        mail_value, 
                        selected_row.get('Piloto', 'N/A'), 
                        analista_value, 
                        selected_row.get('ID-partido', 'sin_id'),
                        adjuntos
                    ):
                        st.success("Correo con PDF enviado correctamente.")
                        
                        # Actualizar Airtable a 'Verificado'
                        at_update = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                        record_id = selected_row.get('Rec')
                        at_update.update('Confirmaciones_de_Entrega', record_id, {
                            'Verificado': 'Verificado',
                            'PDF': [{'url': pdf_url}],
                            'Hash_PDF': pdf_hash
                        })
                        st.success("Registro de Airtable actualizado a 'Verificado' y el PDF subido.")
                        
                        conectar_a_airtable.clear() # Clear cache to fetch new data
                        st.info("Proceso finalizado. El estado ha sido actualizado. Presiona 'Rerun' para ver los cambios.")
                        
                        # Limpiamos las variables de estado
                        del st.session_state["registro_actualizado"]
                        del st.session_state["codigo_generado"]
                        del st.session_state["mail_value_for_pdf"]
                        del st.session_state["analista_value_for_pdf"]
                        del st.session_state["selected_row"]

                        st.rerun()

            except Exception as e:
                st.error(f"Error en el proceso de finalización: {e}")
        else:
            st.error("Código incorrecto. Vuelve a intentarlo.")

def main():
    """Main function to run the Streamlit app."""
    # Check if the process has been initiated
    if st.session_state.get("registro_actualizado"):
        show_code_input()
    else:
        # Load data for the main dashboard
        tabla_entregas = conectar_a_airtable()
        show_main_dashboard(tabla_entregas)

if __name__ == "__main__":
    main()
