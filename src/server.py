# server.py
import os
import secrets
from flask import Flask, request, redirect, url_for
import datetime
from airtable import Airtable

# Importar las funciones necesarias del otro script
# Esta es una convención, asume que 'app' está en un directorio superior
from .app import (
    autenticar_airtable,
    crear_pdf_con_template_en_memoria,
    subir_a_drive_desde_bytes,
    enviar_pdf_confirmacion,
    calcular_hash_bytes,
    DRIVE_FOLDER_ID
)

app = Flask(__name__)
# Usar una variable de entorno para la clave secreta de Flask
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(16))

# Define la URL base de tu aplicación de Render. Es un string fijo.
RENDER_APP_URL = "https://tu-servicio-de-render.onrender.com"

@app.route('/confirmacion')
def confirmar_entrega():
    """
    Endpoint para procesar el token de confirmación de entrega.
    """
    token = request.args.get('token')
    if not token:
        return "Enlace de confirmación no válido.", 400

    try:
        # Buscar el registro en Airtable por el token
        airtable_client = Airtable(os.environ.get("AIRTABLE_BASE_ID"), 'Confirmaciones_de_Entrega', os.environ.get("AIRTABLE_API_KEY"))
        records = airtable_client.get_all(formula=f"{{Token_unico}} = '{token}'")

        if not records:
            return "Token no encontrado o ya ha sido utilizado.", 404

        record = records[0]
        record_fields = record['fields']
        record_id = record['id']

        if record_fields.get('Verificado') == 'Verificado':
            return "Este registro ya ha sido verificado.", 200

        # Ejecutar la lógica de generación y envío del PDF
        fecha_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        pdf_content_without_hash = crear_pdf_con_template_en_memoria(
            record_fields,
            record_fields.get('Analista(Form)'),
            record_fields.get('Codigo_unico'),
            fecha_utc=fecha_utc,
            incluir_hash=False
        )
        pdf_hash = calcular_hash_bytes(pdf_content_without_hash)
        final_pdf_content = crear_pdf_con_template_en_memoria(
            record_fields,
            record_fields.get('Analista(Form)'),
            record_fields.get('Codigo_unico'),
            pdf_hash=pdf_hash,
            fecha_utc=fecha_utc,
            incluir_hash=True
        )

        file_name = f"reporte_{record_fields.get('ID-partido')}.pdf"
        pdf_url = subir_a_drive_desde_bytes(final_pdf_content, file_name, DRIVE_FOLDER_ID)

        if pdf_url:
            adjuntos = [{'nombre': file_name, 'contenido': final_pdf_content}]
            enviar_pdf_confirmacion(
                record_fields.get('Mail(Form)'),
                record_fields.get('Piloto'),
                record_fields.get('Analista(Form)'),
                record_fields.get('ID-partido'),
                adjuntos
            )

        # Actualizar Airtable a 'Verificado'
        fields_to_update = {
            'Verificado': 'Verificado',
            'PDF': [{'url': pdf_url}],
            'Hash_PDF': pdf_hash,
            'Token_unico': '' # Opcional: limpiar el token para que no se use de nuevo
        }
        airtable_client.update(record_id, fields_to_update)

        # Redirigir a una página de confirmación
        return "¡La entrega ha sido confirmada exitosamente! Ya puedes cerrar esta ventana."
        
    except Exception as e:
        return f"Ocurrió un error al procesar la confirmación: {e}", 500

# Esta línea solo se usa para desarrollo local
# if __name__ == '__main__':
#     app.run(debug=True)
