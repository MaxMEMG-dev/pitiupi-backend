from fastapi import APIRouter, Request
from payments_core import mark_intent_paid

router = APIRouter()

@router.post("/nuvei/callback")
async def nuvei_callback(request: Request):
    data = await request.json()

    try:
        order = data.get("order", {})
        transaction = data.get("transaction", {})

        intent_id = order.get("dev_reference")  # nuestro intent local
        provider_tx_id = transaction.get("id")
        status = transaction.get("status")
        status_detail = transaction.get("status_detail")
        authorization_code = transaction.get("authorization_code", "")

        # Validación oficial Nuvei
        if status == "success" and status_detail == 3:
            mark_intent_paid(
                intent_id=int(intent_id),
                provider_tx_id=provider_tx_id,
                status_detail=status_detail,
                authorization_code=authorization_code,
            )

            print(f"[Nuvei] Pago confirmado para intent {intent_id}")

    except Exception as e:
        print("[Nuvei webhook ERROR]", e)

    return {"status": "OK"}
