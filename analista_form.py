# -*- coding: utf-8 -*-
"""
Created on Sun Aug 10 09:38:21 2025

@author: dsanm
"""

import streamlit as st
import pandas as pd
import os
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
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from airtable import Airtable

# Importaciones para la mejora del PDF
from jinja2 import Template
from weasyprint import HTML, CSS

# --- Configuración de la aplicación ---
st.set_page_config(page_title="Dashboard de Entregas", page_icon="✅", layout="wide")
st.title("✅ Dashboard de Confirmaciones de Entrega")

# --- LÓGICA DE INICIO DE SESIÓN ---
# Se utiliza st.session_state para mantener el estado de autenticación.
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# Cargar la contraseña de forma segura desde st.secrets.
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
    
    st.stop() # Detiene la ejecución si el usuario no está autenticado


# --- APIs DE GOOGLE ---
SCOPES_GMAIL = ['https://www.googleapis.com/auth/gmail.send']
SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
DRIVE_FOLDER_ID = "1yNFgOvRclge1SY9QtvnD980f3-4In_hs"

def get_creds(scopes):
    """
    Gestiona la autenticación de Google utilizando un token de refresco
    guardado en st.secrets, para evitar el flujo de servidor local.
    """
    creds = None
    try:
        # Intenta cargar credenciales desde st.secrets
        creds_info = st.secrets.get("google_creds")
        if creds_info and "token" in creds_info and "refresh_token" in creds_info:
            creds = Credentials.from_authorized_user_info(info=creds_info, scopes=scopes)

            # Si el token ha expirado, refresca
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
    """Autentica y devuelve el servicio de la API de Gmail."""
    creds = get_creds(SCOPES_GMAIL)
    if creds:
        return build('gmail', 'v1', credentials=creds)
    return None

def autenticar_drive():
    """Autentica y devuelve el servicio de la API de Google Drive."""
    creds = get_creds(SCOPES_DRIVE)
    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

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

def envia_mail(mail_value, nombre_completo, codigo, nombre_analista, adjuntos=None):
    """Envía un correo electrónico con o sin adjuntos."""
    try:
        service_gmail = autenticar_gmail()
        if not service_gmail:
            return False
            
        remitente = 'me'  # La cuenta que estás autenticando
        asunto = 'Confirmación de entrega de imágenes'
        
        cuerpo = f"""
        <html>
        <head></head>
        <body>
            <p>Hola {nombre_completo},</p>
            {"<p>El código para terminar el proceso es: <b>" + codigo + "</b></p>" if codigo else ""}
            {"<p>Se adjunta un certificado de la entrega.</p>" if adjuntos else ""}
        </body>
        </html>
        """
        
        mensaje = crear_mensaje(remitente, mail_value, asunto, cuerpo, adjuntos)
        enviar_mensaje(service_gmail, remitente, mensaje)
        return True
    except Exception as e:
        st.error(f"No se pudo enviar el correo: {e}")
        return False

# --- FUNCIÓN MEJORADA PARA CREAR EL PDF USANDO PLANTILLA HTML ---
def crear_pdf_con_template(selected_row):
    """
    Genera un PDF de reporte utilizando una plantilla HTML y Jinja2.
    Retorna la ruta del archivo PDF temporal creado.
    """
    # 1. Definir la plantilla HTML
    html_template = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Reporte de Confirmación de Entrega</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px;
                color: #333;
            }
            .header {
                text-align: center;
                border-bottom: 2px solid #007bff;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }
            .header h1 {
                color: #007bff;
            }
            .content {
                line-height: 1.6;
            }
            .field-row {
                margin-bottom: 10px;
            }
            .field-name {
                font-weight: bold;
                color: #555;
            }
            .field-value {
                margin-left: 10px;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Reporte de Confirmación de Entrega</h1>
        </div>
        <div class="content">
            <div class="field-row">
                <span class="field-name">ID-partido:</span>
                <span class="field-value">{{ row['ID-partido'] }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Analista:</span>
                <span class="field-value">{{ row['Analista'] }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Piloto:</span>
                <span class="field-value">{{ row['Piloto'] }}</span>
            </div>
            <div class="field-row">
                <span class="field-name">Fecha Partido:</span>
                <span class="field-value">{{ row['Fecha partido'] }}</span>
            </div>
            <!-- Puedes añadir más campos de Airtable aquí si lo deseas -->
        </div>
    </body>
    </html>
    """

    # 2. Renderizar la plantilla con los datos
    template = Template(html_template)
    html_out = template.render(row=selected_row)

    # 3. Convertir el HTML a PDF
    pdf_content = HTML(string=html_out).write_pdf()

    # 4. Guardar el PDF en un archivo temporal
    file_path = f"reporte_{selected_row.get('ID-partido', 'sin_id')}.pdf"
    with open(file_path, "wb") as f:
        f.write(pdf_content)

    return file_path


# --- Función para subir el PDF a Drive (modificada) ---
def subir_a_drive(file_path, folder_id):
    """Sube un archivo a Google Drive, lo hace público y devuelve su enlace de visualización."""
    servicio_drive = autenticar_drive()
    if not servicio_drive:
        return None

    file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    try:
        archivo = servicio_drive.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        st.success(f"Archivo subido a Google Drive. ID: {archivo.get('id')}")

        # Hacer el archivo público para que Airtable pueda acceder
        servicio_drive.permissions().create(
            fileId=archivo.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            fields='id'
        ).execute()

        # Devolver webContentLink para la columna de Airtable
        return archivo.get('webContentLink')
    except Exception as e:
        st.error(f"Error al subir o compartir el archivo: {e}")
        return None


# --- API DE AIRTABLE ---
# Airtable credentials
AIRTABLE_API_KEY = st.secrets["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = st.secrets["AIRTABLE_BASE_ID"]
airtable = Airtable(AIRTABLE_BASE_ID, 'analista', AIRTABLE_API_KEY)


# --- CÓDIGO PRINCIPAL DE LA APLICACIÓN (SÓLO PARA USUARIOS AUTENTICADOS) ---

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
    
    if st.button("Envío"):
        if codigo_ingresado == st.session_state.get("codigo_generado"):
            st.success("Código correcto. Procediendo con el envío del PDF.")
            
            if 'selected_row' in st.session_state:
                selected_row = st.session_state['selected_row']
                mail_value = selected_row.get('Mail', '')
                #analista_value = selected_row.get('Analista', '')
                analista_value = analista_value_input
                
                # Generar el PDF de reporte con la nueva función
                with st.spinner("Generando PDF y subiendo a Google Drive..."):
                    pdf_file_path = crear_pdf_con_template(selected_row)
                    pdf_url = subir_a_drive(pdf_file_path, DRIVE_FOLDER_ID)
                
                if pdf_file_path and pdf_url:
                    # Preparar el adjunto para el correo
                    with open(pdf_file_path, "rb") as f:
                        adjuntos = [{'nombre': os.path.basename(pdf_file_path), 'contenido': f.read()}]
                    
                    # Enviar el PDF por mail y actualizar Airtable
                    if mail_value and envia_mail(mail_value, selected_row.get('Nombre_Completo', ''), "", analista_value, adjuntos):
                        st.success("Correo con PDF enviado correctamente.")
                        # Actualizar Airtable
                        at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                        record_id = selected_row.get('Rec')
                        if record_id:
                            fields_to_update = {
                                'Verificado': 'Verificado',
                                'PDF': [{'url': pdf_url}]
                            }
                            at_Table1.update('vuelos_programados_dia', record_id, fields_to_update)
                            st.success("Registro de Airtable actualizado a 'Verificado' y el PDF subido.")
                            
                            # LIMPIAR EL CACHÉ DE AIRTABLE
                            conectar_a_airtable.clear()
                            
                        else:
                            st.error("No se pudo obtener el ID del registro para actualizar Airtable.")
                            
                    # Eliminar el archivo local
                    if os.path.exists(pdf_file_path):
                        os.remove(pdf_file_path)
            else:
                st.error("No se pudo recuperar el registro. Por favor, reinicia el proceso.")
                
            # Limpiar la sesión para volver a la pantalla principal
            if "registro_actualizado" in st.session_state:
                del st.session_state["registro_actualizado"]
            st.rerun()
        else:
            st.error("Código incorrecto. Vuelve a intentarlo.")
    st.stop()

# --- Pantalla principal ---
if not tabla_entregas.empty:
    partidos = tabla_entregas['ID-partido'].unique().tolist()
    opcion_seleccionada = st.selectbox('Selecciona un ID de partido', options=partidos)
    df_filtrado = tabla_entregas[tabla_entregas['ID-partido'] == opcion_seleccionada]

    if not df_filtrado.empty:
        selected_row = df_filtrado.iloc[0]
        # Guardar la fila seleccionada en el estado de la sesión para usarla después
        st.session_state['selected_row'] = selected_row
        
        with st.form("update_form"):
            analista_value = selected_row.get('Analista', '')
            sin_analista = False
            if pd.isna(analista_value) or not analista_value:
                sin_analista = True
                analista_value_input = st.text_input("Analista (Manual)", value="", placeholder="Analista")
            else:
                #st.text_input("Analista (Airtable)", value=analista_value, disabled=True)
                #analista_value_input = analista_value # Usar el valor de Airtable si existe
                analista_value_input = st.text_input("Analista (Airtable)", value=analista_value, disabled=False) # Usar el valor de Airtable si existe

            st.text_input("Piloto", value=selected_row.get('Piloto', 'N/A'), disabled=True)
            st.text_input("Fecha Partido", value=selected_row.get('Fecha partido', 'N/A'), disabled=True)

            mail_value = selected_row.get('Mail', '')
            sin_mail = False
            if pd.isna(mail_value) or not mail_value:
                sin_mail = True
                mail_value_input = st.text_input("Mail (Manual)", value="", placeholder="Introduce el correo...")
            else:
                st.text_input("Mail (Airtable)", value=mail_value, disabled=True)
                mail_value_input = mail_value # Usar el valor de Airtable si existe

            verificado = st.checkbox("Marcar como Verificado")
            submitted = st.form_submit_button("Actualizar Registro")

        if submitted:
            if verificado:
                # Validar campos manuales antes de continuar
                if (sin_analista and not analista_value_input) or (sin_mail and not mail_value_input):
                    st.warning("El nombre del analista y el correo son obligatorios si no están en Airtable.")
                else:
                    random_code = random.randint(100000, 999999)

                    # Actualizar Airtable
                    at_Table1 = Airtable(st.secrets["AIRTABLE_BASE_ID"], st.secrets["AIRTABLE_API_KEY"])
                    record_id = selected_row.get('Rec')
                    if record_id:
                        fields_to_update = {}
                        if sin_analista:
                            fields_to_update['Analista'] = analista_value_input
                        elif analista_value != analista_value_input:
                            fields_to_update['Analista'] = analista_value_input
                        if sin_mail:
                            fields_to_update['Mail'] = mail_value_input
                        
                        fields_to_update['Verificado'] = 'Pendiente'
                        at_Table1.update('vuelos_programados_dia', record_id, fields_to_update)

                        if not mail_value_input or pd.isna(mail_value_input):
                            st.error("No hay correo válido para enviar el código.")
                        else:
                            try:
                                # Envía el correo SÓLO con el código (sin adjuntos)
                                if envia_mail(mail_value_input, selected_row.get('Nombre_Completo', ''), str(random_code), analista_value_input):
                                    st.success(f"Correo enviado a {mail_value_input}")
                                    # Guardar estado para mostrar la pantalla de código
                                    st.session_state["registro_actualizado"] = True
                                    st.session_state["codigo_generado"] = str(random_code)
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








