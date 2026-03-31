"""
caller.py — Iniciador de Llamadas Salientes (Rapilink — Campaña Upgrade)
Motor: LiveKit SIP Outbound

Uso desde n8n (ejecutar en VPS):
    python caller.py --phone "+573001234567" --room "upgrade-abc123" --meta '{"nombre":"Juan","categoria":"A",...}'

Uso programático desde Python:
    asyncio.run(dial_client(phone="+573001234567", room_name="upgrade-abc123", client_meta={...}))

Flujo:
1. Crea un Room en LiveKit (o usa uno existente).
2. Llama al número del cliente vía el troncal SIP de Issabel configurado en LiveKit.
3. El cliente entra al room y el agente (agent.py) lo atiende.
"""

import argparse
import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from livekit import api

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sofia-caller")

LIVEKIT_URL        = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
SIP_TRUNK_ID       = os.getenv("SIP_OUTBOUND_TRUNK_ID")


async def dial_client(
    phone: str,
    room_name: str,
    client_meta: dict,
) -> dict:
    """
    Despacha una llamada saliente a `phone` usando el troncal SIP configurado.
    Los datos del cliente se inyectan como metadatos del Room para que agent.py los use.

    Returns:
        dict con el resultado de la operación.
    """

    # ── Validaciones Zero Trust ──────────────────────────────────────────────
    if not phone or phone == "None":
        logger.error("[MAPPING] phone es undefined/None — abortando llamada.")
        return {"ok": False, "error": "phone_invalido"}

    if not SIP_TRUNK_ID or SIP_TRUNK_ID.startswith("ST_xxx"):
        logger.error("[MAPPING] SIP_OUTBOUND_TRUNK_ID no configurado — abortando.")
        return {"ok": False, "error": "trunk_no_configurado"}

    nombre = client_meta.get("nombre", "DESCONOCIDO")
    id_wisphub = client_meta.get("id_cliente_wisphub", "?")

    logger.info("[INTERNAL] ID WispHub: %s | Nombre: %s", id_wisphub, nombre)
    logger.info("[REQUEST] Marcando %s → Room: %s | Trunk: %s", phone, room_name, SIP_TRUNK_ID)

    # ── Crear Room (con los metadatos del cliente para agent.py) ────────────
    meta_json = json.dumps(client_meta)

    lk = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        # Crear el room con metadatos
        await lk.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=meta_json,
                empty_timeout=300,          # Cerrar el room si está vacío 5 min
                max_participants=5,
            )
        )
        logger.info("[REQUEST] Room '%s' creado con metadatos del cliente.", room_name)

        # ── Despachar la llamada SIP saliente ────────────────────────────────
        await lk.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=SIP_TRUNK_ID,
                sip_call_to=phone,                          # Número en formato E.164 (+57...)
                room_name=room_name,
                participant_identity=f"cliente_{id_wisphub}",
                participant_name=nombre,
                # Esperar a que el cliente conteste antes de conectar el audio
                wait_until_answered=True,
            )
        )

        logger.info("[RESPONSE] Llamada a %s despachada correctamente.", phone)
        return {"ok": True, "room": room_name, "phone": phone}

    except Exception as e:
        logger.error("[ERROR] Fallo al marcar %s: %s", phone, e)
        return {"ok": False, "error": str(e)}

    finally:
        await lk.aclose()


# ─────────────────────────────────────────────
# CLI (para llamar desde n8n vía SSH o subprocess)
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Caller de llamadas salientes Sofía")
    parser.add_argument("--phone",  required=True, help="Número destino en formato E.164 (+573001234567)")
    parser.add_argument("--room",   required=True, help="Nombre único del Room (ej: upgrade-abc123)")
    parser.add_argument("--meta",   required=True, help="JSON con datos del cliente")
    args = parser.parse_args()

    try:
        client_meta = json.loads(args.meta)
        # Si el input vino como string doblemente escapado (común en Docker/Dokploy), re-parsear
        if isinstance(client_meta, str):
            client_meta = json.loads(client_meta)
    except json.JSONDecodeError as e:
        logger.error("[ERROR] --meta no es JSON válido: %s", e)
        raise SystemExit(1)

    result = asyncio.run(dial_client(
        phone=args.phone,
        room_name=args.room,
        client_meta=client_meta,
    ))

    # Salida para que n8n la lea
    print(json.dumps(result))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
