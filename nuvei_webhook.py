from fastapi import APIRouter, Request, HTTPException
from payments_core import mark_intent_paid, update_payment_intent, get_payment_intent
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/nuvei/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[Nuvei] Webhook recibido: {payload}")

        # Validación principal
        if "data" not in payload:
            logger.error("Webhook inválido: falta 'data'")
            return {"status": "OK"}

        data = payload["data"]

        # Extraer order
        order = data.get("order", {})
        transaction = data.get("transaction", {})

        intent_id = order.get("dev_reference")  # ID interno
        order_id = order.get("id")              # ID de Nuvei

        provider_tx_id = transaction.get("id")
        status = transaction.get("status")
        status_detail = transaction.get("status_detail")
        authorization_code = transaction.get("authorization_code")

        if not intent_id:
            logger.error("Webhook sin dev_reference (intent_id)")
            return {"status": "OK"}

        intent_id = int(intent_id)

        # Guardar el order_id si no lo teníamos
        existing = get_payment_intent(intent_id)
        if existing and not existing["order_id"]:
            update_payment_intent(intent_id, order_id=order_id)

        # Validar pago aprobado
        if status == "success" and status_detail == 3:
            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=provider_tx_id,
                status_detail=status_detail,
                authorization_code=authorization_code
            )

            logger.info(f"[Nuvei] Pago aprobado para intent {intent_id}")

        else:
            logger.info(f"[Nuvei] Pago no aprobado: status={status} detail={status_detail}")

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {e}")

    return {"status": "OK"}   # SIEMPRE devolver OK
