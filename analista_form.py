# -*- coding: utf-8 -*-
"""
Created on Sun Aug 10 09:38:21 2025

@author: dsanm
"""

import streamlit as st
import pandas as pd
import os
import re
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
from datetime import datetime
import hashlib
from weasyprint import HTML

# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML, CSS
import base64

# Importación de Airtable
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
    import base64
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        st.error(f"Error: No se encontró la imagen en la ruta {image_path}")
        return None

# --- IMPROVED PDF CREATION FUNCTION USING HTML TEMPLATE ---
def crear_pdf_con_template(selected_row, analista_value, codigo_unico):
    """
    Genera un PDF con un template HTML que incluye:
      - Logo (si está disponible, embebido en base64)
      - Datos principales (ID-partido, Analista, Piloto, Fecha, Código único)
      - Anexo Legal (texto estándar) con marca temporal UTC ISO y hash SHA256 del PDF final
    """

    logo_path = "./img/logo.png"
    try:
        with open(logo_path, "rb") as image_file:
            import base64
            base64_logo = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception:
        base64_logo = None

    fecha_utc = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    anexo_legal = f"""
    <h3>Anexo Legal — Declaración de Recepción y Custodia del Material</h3>
    <p>La introducción del código único proporcionado por este sistema y la confirmación de
    su recepción constituyen una <strong>aceptación expresa</strong> de la entrega física
    del material identificado en este documento, así como la asunción de su custodia.</p>
    <p>Esta confirmación constituye una firma electrónica simple y queda asociada a la
    identidad del receptor, el código único, la fecha y hora de confirmación y la
    descripción del material entregado. El registro se conserva para fines de auditoría
    y resolución de disputas.</p>
    <p>Fly-Fut S.L. se reserva el derecho a presentar esta documentación como prueba ante
    cualquier autoridad administrativa o judicial competente.</p>
    """

    html_template = f"""
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
            .field-name {{ font-weight: bold; color: #555; width: 180px; display: inline-block; }}
            .field-value {{ margin-left: 10px; }}
            .logo {{ width: 150px; margin-bottom: 20px; }}
            .anexo {{ margin-top: 30px; font-size: 12px; color: #444; border-top: 1px solid #ddd; padding-top: 12px; }}
            .meta {{ font-family: monospace; font-size: 11px; color: #666; margin-top: 8px; }}
        </style>
    </head>
    <body>
        <div class="header">
            {f'<img src="data:image/png;base64,{base64_logo}" alt="Logo" class="logo">' if base64_logo else ''}
            <h1>Reporte de Confirmación de Entrega</h1>
        </div>

        <div class="content">
            <div class="field-row"><span class="field-name">ID-partido:</span><span class="field-value">{selected_row.get('ID-partido', '')}</span></div>
            <div class="field-row"><span class="field-name">Analista:</span><span class="field-value">{analista_value}</span></div>
            <div class="field-row"><span class="field-name">Piloto:</span><span class="field-value">{selected_row.get('Piloto', '')}</span></div>
            <div class="field-row"><span class="field-name">Fecha Partido:</span><span class="field-value">{selected_row.get('Fecha partido', '')}</span></div>
            <div class="field-row"><span class="field-name">Código Único:</span><span class="field-value" style="font-family: monospace;">{codigo_unico}</span></div>

            <div class="anexo">
                {anexo_legal}
                <div class="meta">
                    <div>Fecha/hora UTC de generación: <strong>{fecha_utc}</strong></div>
                    <div>Hash (SHA256) del PDF final: <strong>{{PDF_HASH}}</strong></div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    pdf_content = HTML(string=html_template).write_pdf()

    pdf_hash = hashlib.sha256(pdf_content).hexdigest()
    html_with_hash = html_template.replace('{{PDF_HASH}}', pdf_hash)
    pdf_content_final = HTML(string=html_with_hash).write_pdf()

    safe_id = str(selected_row.get('ID-partido', 'sin_id')).replace(' ', '_')
    file_path = f"reporte_{safe_id}_{codigo_unico}.pdf"
    with open(file_path, 'wb') as f:
        f.write(pdf_content_final)

    return file_path

# --- Function to upload PDF to Drive (modified) ---
def subir_a_drive(file_path, folder_id):
    """
    Uploads a file to Google Drive, makes it public, and returns its view link.
    """
    servicio_drive = autenticar_drive()
    if not servicio_drive:
        return None

    file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
    media = MediaFileUpload(file_path, mimetype='application/pdf')
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

        # CORRECCIÓN: Asegurar que tipo_evento sea una cadena de texto
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
            <p>Para completar este protocolo de seguridad y asegurar la cadena de custodia del material, por favor, facilita el siguiente código único al piloto cuando recibas la tarjeta:</p>

            <h2 style="text-align: center; color: #007bff; border: 2px solid #007bff; padding: 10px; font-family: monospace;">{codigo}</h2>

            <hr style="border: 0; border-top: 1px solid #ccc; margin: 30px 0;">

            <h4>Declaración de No Repudio y Validez Legal</h4>
            <p>Al facilitar este código al piloto, usted está confirmando la recepción y aceptación de la custodia de la tarjeta SD. Esta acción genera un registro digital con fecha y hora, que certifica la entrega del material.</p>
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

@st.cache_data(ttl=600)
def conectar_a_airtable():
    at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
    result_at_Table1 = at_Table1.get('Confirmaciones_de_Entrega', view='Grid view')
    airtable_rows = [r['fields'] for r in result_at_Table1['records']]
    df = pd.DataFrame(airtable_rows)
    return df

tabla_entregas = conectar_a_airtable()

# --- Show code input screen if already updated ---
if st.session_state.get("registro_actualizado"):
    st.subheader("Introduce el código enviado al analista")
    codigo_ingresado = st.text_input("Código")
    
    if st.button("Envío"):
        if codigo_ingresado == st.session_state.get("codigo_generado"):
            st.success("Código correcto. Procediendo con el envío del PDF.")
            
            if 'selected_row' in st.session_state:
                selected_row = st.session_state['selected_row']
                mail_value = st.session_state.get('mail_value_for_pdf', '')
                analista_value = st.session_state.get('analista_value_for_pdf', '')
                
                with st.spinner("Generando PDF y subiendo a Google Drive..."):
                    pdf_file_path = crear_pdf_con_template(selected_row, analista_value, st.session_state["codigo_generado"])
                    pdf_url = subir_a_drive(pdf_file_path, DRIVE_FOLDER_ID)
                
                if pdf_file_path and pdf_url:
                    with open(pdf_file_path, "rb") as f:
                        adjuntos = [{'nombre': os.path.basename(pdf_file_path), 'contenido': f.read()}]
                    
                    if mail_value and enviar_pdf_confirmacion(
                        mail_value, 
                        selected_row.get('Piloto', 'N/A'), 
                        analista_value, 
                        selected_row.get('ID-partido', 'sin_id'),
                        adjuntos
                    ):
                        st.success("Correo con PDF enviado correctamente.")
                        
                        at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                        record_id = selected_row.get('Rec')
                        if record_id:
                            fields_to_update = {
                                'Verificado': 'Verificado',
                                'PDF': [{'url': pdf_url}]
                            }
                            at_Table1.update('Confirmaciones_de_Entrega', record_id, fields_to_update)
                            st.success("Registro de Airtable actualizado a 'Verificado' y el PDF subido.")
                            
                            conectar_a_airtable.clear()
                        else:
                            st.error("No se pudo obtener el ID del registro para actualizar Airtable.")
                            
                    if os.path.exists(pdf_file_path):
                        os.remove(pdf_file_path)
            else:
                st.error("No se pudo recuperar el registro. Por favor, reinicia el proceso.")
                
            if "registro_actualizado" in st.session_state:
                del st.session_state["registro_actualizado"]
                if "mail_value_for_pdf" in st.session_state: del st.session_state["mail_value_for_pdf"]
                if "analista_value_for_pdf" in st.session_state: del st.session_state["analista_value_for_pdf"]
                st.rerun()
        else:
            st.error("Código incorrecto. Vuelve a intentarlo.")
    st.stop()

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
            
            verificado = st.checkbox("Marcar como Verificado")
            submitted = st.form_submit_button("Actualizar Registro")

        if submitted:
            if verificado:
                if not analista_value_input or not mail_value_input:
                    st.warning("El nombre del analista y el correo son obligatorios.")
                else:
                    random_code = random.randint(100000, 999999)

                    # Update Airtable
                    at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                    record_id = selected_row.get('Rec')
                    if record_id:
                        fields_to_update = {
                            'Analista(Form)': analista_value_input,
                            'Mail(Form)': mail_value_input,
                            'Verificado': 'Pendiente',
                            'Codigo_unico': str(random_code),
                        }
                        at_Table1.update('Confirmaciones_de_Entrega', record_id, fields_to_update)
                        
                        st.success("Registro de Airtable actualizado a 'Pendiente'.")

                        if not mail_value_input or pd.isna(mail_value_input):
                            st.error("No hay correo válido para enviar el código.")
                        else:
                            try:
                                if envia_mail(
                                    mail_value_input, 
                                    selected_row.get('Piloto', ''), 
                                    str(random_code), 
                                    analista_value_input, 
                                    selected_row.get('ID-partido', 'sin_id'),
                                    selected_row.get('Fecha partido', 'sin fecha'),
                                    selected_row.get('Tipo', 'evento')
                                ):
                                    st.success(f"Correo enviado a {mail_value_input} con el código de confirmación.")
                                    
                                    # Save state for the code screen and for the PDF generation
                                    st.session_state["registro_actualizado"] = True
                                    st.session_state["codigo_generado"] = str(random_code)
                                    st.session_state["mail_value_for_pdf"] = mail_value_input
                                    st.session_state["analista_value_for_pdf"] = analista_value_input
                                    st.session_state["selected_row"] = selected_row

                                    st.rerun()
                            except Exception as e:
                                st.error(f"No se pudo enviar el correo: {e}")
                    else:
                        st.error("No se pudo obtener el ID del registro.")
            else:
                st.warning("Debes marcar 'Marcar como Verificado' para iniciar el proceso.")
    else:
        st.warning("No se encontraron registros para el partido seleccionado.")
else:
    st.warning("No se encontraron datos en la tabla.")
























