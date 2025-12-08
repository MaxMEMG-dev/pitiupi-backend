from fastapi import APIRouter, Request, HTTPException
import hashlib
import logging
import os

from payments_core import (
    mark_intent_paid,
    update_payment_intent,
    get_payment_intent
)

router = APIRouter()
logger = logging.getLogger(__name__)

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")


def generate_stoken(transaction_id: str, user_id: str) -> str:
    raw = f"{transaction_id}_{APP_CODE}_{user_id}_{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


@router.post("/nuvei/callback")
async def nuvei_callback(request: Request):
    """
    Webhook oficial de Nuvei LinkToPay.
    Recibe los datos reales del pago, valida el stoken y actualiza la DB.
    """
    try:
        payload = await request.json()
        logger.info(f"[Nuvei] Webhook recibido: {payload}")

        if "transaction" not in payload:
            logger.error("❌ Webhook inválido: falta 'transaction'")
            return {"status": "OK"}

        transaction = payload["transaction"]
        user_data = payload.get("user", {})

        # -----------------------------------------------
        # EXTRAER DATOS IMPORTANTES
        # -----------------------------------------------
        transaction_id = transaction.get("id")
        status = transaction.get("status")               # "1" = success
        status_detail = transaction.get("status_detail") # "3" = approved
        dev_reference = transaction.get("dev_reference") # Nuestro intent_id
        authorization_code = transaction.get("authorization_code")

        user_id = user_data.get("id")  # Telegram ID que enviamos

        if not dev_reference:
            logger.error("❌ Webhook sin dev_reference")
            return {"status": "OK"}

        intent_id = int(dev_reference)

        # -----------------------------------------------
        # VALIDAR STOKEN
        # -----------------------------------------------
        sent_stoken = transaction.get("stoken")
        correct_stoken = generate_stoken(transaction_id, user_id)

        if sent_stoken != correct_stoken:
            logger.error("❌ ERROR: STOKEN inválido, webhook rechazado")
            return {"status": "OK"}   # No devolver error 500 o Nuvei reintenta

        # -----------------------------------------------
        # GUARDAR order_id SI EXISTE
        # -----------------------------------------------
        existing = get_payment_intent(intent_id)
        if existing and not existing["order_id"]:
            ltp_id = transaction.get("ltp_id")
            if ltp_id:
                update_payment_intent(intent_id, order_id=ltp_id)

        # -----------------------------------------------
        # VALIDAR ESTADO DE APROBACIÓN
        # -----------------------------------------------
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago APROBADO para intent {intent_id}")

            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=status_detail,
                authorization_code=authorization_code
            )
        else:
            logger.warning(f"🔶 Pago no aprobado: status={status}, detail={status_detail}")

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {str(e)}", exc_info=True)
        return {"status": "OK"}  # Nunca enviar error a Nuvei
