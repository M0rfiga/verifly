import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
service_account_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

if service_account_json:
    cred = credentials.Certificate(json.loads(service_account_json))
elif service_account_file:
    cred = credentials.Certificate(service_account_file)
else:
    raise RuntimeError(
        "Configure FIREBASE_SERVICE_ACCOUNT_JSON no servidor ou "
        "GOOGLE_APPLICATION_CREDENTIALS com o caminho da chave na máquina local."
    )

firebase_admin.initialize_app(cred)

db = firestore.client()
