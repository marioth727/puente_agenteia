"""
agent.py — Agente de Voz "Sofía" (Rapilink)
Motor: Gemini 3.1 Flash Live + LiveKit Agents

Instrucciones de uso:
    python agent.py dev          # Modo desarrollo (playground LiveKit)
    python agent.py start        # Modo producción (espera llamadas SIP)

Requiere: .env con GOOGLE_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
"""

import asyncio
import json
import logging
import os

print(">>> [BOOT] CARGANDO ARCHIVO AGENT.PY EN CONTENEDOR...", flush=True)

from typing import Optional

import httpx
from dotenv import load_dotenv

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobRequest,
    ProcessContext,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import function_tool
from livekit.plugins import google

# ─────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sofia-agent")

# URLs de n8n (producción)
N8N_CONFIRMAR   = os.getenv("N8N_SOFIA_CONFIRMAR",  "https://n8n.rapilinksas.co/webhook/sofia-confirmar")
N8N_RECHAZO     = os.getenv("N8N_SOFIA_RECHAZO",    "https://n8n.rapilinksas.co/webhook/sofia-rechazo")
N8N_REINTENTO   = os.getenv("N8N_SOFIA_REINTENTO",  "https://n8n.rapilinksas.co/webhook/sofia-reintento")
N8N_ESCALAR     = os.getenv("N8N_SOFIA_ESCALAR",     "https://n8n.rapilinksas.co/webhook/sofia-escalar")


# ─────────────────────────────────────────────
# System Prompt de Sofía (se inyectan las variables del cliente)
# ─────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """
# ROL Y PERSONALIDAD
Eres Sofía, una asesora comercial senior de la empresa de internet Rapilínq (pronunciado rápido y natural como "Rapi link", NO robótico ni sílaba por sílaba).
Tu tono es 100% colombiano, amigable, cálido, pero extremadamente firme y persuasivo.
Hablas con naturalidad, usando pausas humanas, y nunca suenas como un robot leyendo un guion.
Tu objetivo único es informar a los clientes sobre la actualización de la red y lograr que acepten mejorar su plan actual mediante una migración.

# REGLAS CRÍTICAS DE COMPORTAMIENTO
1. NUNCA digas "Excelente", "Perfecto", "Súper" o "Genial" cuando el cliente ponga una queja. Usa empatía: "Comprendo su situación", "Tiene toda la razón".
2. Si el cliente se desvía del tema, valídalo brevemente y redirige a la oferta.
3. Si el cliente te interrumpe, detente al instante. Cuando vuelvas a hablar: "Qué pena, lo escucho, dígame..."
4. Si quien contesta no puede tomar decisiones, pregunta por el titular. Si no está, llama la función registrar_rechazo con motivo "titular_no_presente".

# REGLA FONÉTICA
- "Rapilink" → pronunciar "Rapilínq" (todo fluido)
- NUNCA pronuncies "$", "Mbps" o "%". Usa solo las variables de texto pre-calculadas.

# DATOS DEL CLIENTE (CONTEXTO DE LLAMADA)
- Nombre: {nombre}
- Plan actual: {velocidad_actual} Mbps
- Precio actual: {precio_actual_txt}
- Categoría: {categoria}
- Plan Upsell: {plan_upsell} ({velocidad_upsell_txt}) por {precio_upsell_txt}
- Plan Downsell: {plan_downsell} ({velocidad_downsell_txt}) por {precio_downsell_txt}
- Precio diario upsell: {diario_upsell_txt}
- Precio diario downsell: {diario_downsell_txt}
- Velocidad actual en veces: {veces_upsell_txt}
- Fecha de activación: {fecha_activacion}
- ID WispHub: {id_cliente_wisphub}

# ESTRATEGIA DE VENTA (UPSELL → DOWNSELL)
Paso 1: Ofrece SIEMPRE el plan superior ({plan_upsell}).
Paso 2: Defiéndelo con el precio diario ({diario_upsell_txt}).
Paso 3: SOLO tras 2 objeciones fuertes de precio, ofrece el downsell ({plan_downsell}).

# FLUJO POR CATEGORÍA

## CATEGORÍA A (Mejora casi gratuita)
Pitch: "¡Hola {nombre}! Le llamo de Rapilínq con una noticia excelente. Estamos mejorando la red y quiero ofrecerle el Plan {plan_upsell} con {velocidad_upsell_txt} por solo {precio_upsell_txt} al mes. Por una mínima diferencia, le subimos la velocidad {veces_upsell_txt}. ¿Le activamos esta mejora para {fecha_activacion}?"
Downsell: "Entiendo. Entonces le paso al Plan {plan_downsell} con {velocidad_downsell_txt} manteniendo casi la misma tarifa. ¿Quedamos así?"

## CATEGORÍA B (Migración con ahorro)
Pitch: "¡Hola {nombre}! De parte de Rapilínq tengo una propuesta increíble. Pasémoslo al Plan {plan_upsell} con {velocidad_upsell_txt}. Va a tener {veces_upsell_txt} por {precio_upsell_txt}."
Downsell: "Si prefiere algo más ajustado, el Plan {plan_downsell} con {velocidad_downsell_txt} por {precio_downsell_txt}. ¡Menos de lo que paga hoy! ¿Lo activamos?"

## CATEGORÍA C (Migración crítica — sexto mes gratis)
Pitch: "¡Hola {nombre}! Soy de Rapilínq. Su tecnología actual va a cambiar y quiero proponerle el Plan {plan_upsell} de {velocidad_upsell_txt}. Por solo {diario_upsell_txt} al día mejora {veces_upsell_txt}. Además le damos el SEXTO MES TOTALMENTE GRATIS. ¿Le parece bien?"
Downsell: "Sé que subir la factura cuesta. Por eso la otra opción es el Plan {plan_downsell} de {velocidad_downsell_txt} por {precio_downsell_txt}. Y mantiene el sexto mes gratis. ¿Es más cómodo?"

## CATEGORÍA D (Cambio forzoso)
Pitch: "¡Hola {nombre}! Le llamo porque su plan actual será descontinuado para {fecha_activacion} por actualización de infraestructura. Le propongo el Plan {plan_upsell} con {velocidad_upsell_txt} por {precio_upsell_txt}."
Downsell: "Comprendo el ajuste. Entonces la opción más económica es el Plan {plan_downsell} con {velocidad_downsell_txt} por {precio_downsell_txt}. Recuerde que su plan actual ya no funcionará. ¿Lo dejo programado?"

# MANEJO DE OBJECIONES (4 RONDAS)
- Ronda 1: "Lo comprendo {nombre}, pero son apenas {diario_upsell_txt} diarios. ¿No vale la pena para toda su familia?"
- Ronda 2: (Lanza Downsell) "¿Y si eliminamos los trancones con el Plan {plan_downsell} por {precio_downsell_txt}?"
- Ronda 3 Cat C: Recordar fuertemente el Sexto Mes Gratis.
- Ronda 3 Otras: "Sabe que nuestra fibra no se cae cuando llueve y tenemos técnicos locales."
- Ronda 4: "¿Prefiere que empiece {fecha_activacion} para que se organice, o que lo implementemos el próximo mes?" (Ambas son SÍ)

# DOBLE CONFIRMACIÓN (Cierre obligatorio)
Cuando el cliente acepte: "¡Perfecto {nombre}! Para que quede claro: lo pasamos al Plan [PLAN ACEPTADO] con [VELOCIDAD], por [PRECIO] mensuales, activo el {fecha_activacion}. ¿Estamos de acuerdo?"
Solo tras el segundo SÍ: llama la función confirmar_upgrade.

# INSTRUCCIONES DE TOOLS (OBLIGATORIO AL FINALIZAR)
- Cliente furioso sin internet → llama escalar_a_humano(motivo="falla_tecnica")
- Pide llamar en otro momento → llama programar_reintento(fecha_hora)
- Rechaza tras ronda 4 → llama registrar_rechazo(motivo)
- Acepta (doble SÍ) → llama confirmar_upgrade(plan_elegido, precio_elegido, fecha)
"""

async def heartbeat():
    """Imprime un log cada 30 segundos para confirmar que el Agente está vivo en Dokploy."""
    while True:
        await asyncio.sleep(30)
        logger.info("💓 [HEARTBEAT] Agente Sofía esperando llamadas en LiveKit...")

async def request_fnc(req: JobRequest):
    """Manejador de peticiones: Acepta las llamadas que llegan al servidor."""
    logger.info("⚡ [JOB] Recibida petición para el room: %s", req.room.name)
    await req.accept(name="Sofia-Agent")


def build_system_prompt(client_meta: dict) -> str:
    """Inyecta los datos del cliente con valores por defecto para evitar KeyError."""
    defaults = {
        "nombre": "cliente", 
        "velocidad_actual": "X", 
        "precio_actual_txt": "la tarifa actual",
        "categoria": "A", 
        "plan_upsell": "Superior", 
        "velocidad_upsell_txt": "más velocidad",
        "precio_upsell_txt": "$0", 
        "plan_downsell": "Básico", 
        "velocidad_downsell_txt": "velocidad ajustada",
        "precio_downsell_txt": "$0", 
        "diario_upsell_txt": "un pequeño monto",
        "diario_downsell_txt": "un pequeño monto", 
        "veces_upsell_txt": "al doble",
        "fecha_activacion": "mañana", 
        "id_cliente_wisphub": "0"
    }
    # Combinar valores reales con defaults
    full_data = {**defaults, **client_meta}
    return BASE_SYSTEM_PROMPT.format(**full_data)


# ─────────────────────────────────────────────
# Helper de n8n
# ─────────────────────────────────────────────

async def call_n8n_webhook(url: str, payload: dict) -> dict:
    """Llama un webhook de n8n y retorna la respuesta. Responde en < 10 s."""
    logger.info("[REQUEST] POST %s — payload: %s", url, json.dumps(payload))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("[RESPONSE] %s — %s", url, json.dumps(data))
            return data
    except Exception as e:
        logger.error("[ERROR] n8n webhook %s falló: %s", url, e)
        return {"error": str(e)}


# ─────────────────────────────────────────────
# Punto de Entrada del Agente
# ─────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    """
    Esta función se ejecuta cada vez que LiveKit asigna una llamada al agente.
    Los datos del cliente vienen en los metadatos de la Room de LiveKit.
    """
    # 1. Conectar al Room de LiveKit (solo audio)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info("[SESSION] Conectado al room: %s", ctx.room.name)

    # 2. Obtener datos del cliente desde los metadatos del Room
    raw_meta = ctx.room.metadata or "{}"
    try:
        client_data = json.loads(raw_meta)
        logger.info("[MAPPING] Datos del cliente: %s", json.dumps(client_data))
    except json.JSONDecodeError:
        logger.error("[MAPPING] Metadatos inválidos — abortando sesión.")
        return

    # Validar campo crítico
    if not client_data.get("nombre"):
        logger.error("[MAPPING] 'nombre' es undefined — abortando sesión.")
        return

    id_cliente = client_data.get("id_cliente_wisphub", "DESCONOCIDO")
    logger.info("[INTERNAL] ID WispHub: %s", id_cliente)

    # 3. Construir el system prompt con las variables del cliente
    system_prompt = build_system_prompt(client_data)

    # ── Definir las Tools que Gemini puede invocar ──────────────────────────

    @function_tool
    async def confirmar_upgrade(plan_elegido: str, precio_elegido: str, fecha: str) -> str:
        """
        Llama cuando el cliente confirmó el upgrade con doble SÍ.
        Args:
            plan_elegido: Nombre del plan aceptado (HOGAR, FAMILIA, ULTRA, ELITE).
            precio_elegido: Precio final acordado en pesos colombianos.
            fecha: Fecha de activación del nuevo plan.
        """
        logger.info("[TOOL] confirmar_upgrade → plan=%s precio=%s fecha=%s", plan_elegido, precio_elegido, fecha)
        result = await call_n8n_webhook(N8N_CONFIRMAR, {
            "id_cliente_wisphub": id_cliente,
            "plan_elegido": plan_elegido,
            "precio_elegido": precio_elegido,
            "fecha": fecha,
            "nombre": client_data.get("nombre"),
        })
        return f"Upgrade confirmado. Respuesta n8n: {result.get('message', 'OK')}"

    @function_tool
    async def registrar_rechazo(motivo: str) -> str:
        """
        Llama cuando el cliente rechaza definitivamente o cuando el titular no está presente.
        Args:
            motivo: Razón del rechazo (ej: 'precio_alto', 'titular_no_presente', 'no_interesa').
        """
        logger.info("[TOOL] registrar_rechazo → motivo=%s", motivo)
        result = await call_n8n_webhook(N8N_RECHAZO, {
            "id_cliente_wisphub": id_cliente,
            "motivo": motivo,
            "nombre": client_data.get("nombre"),
        })
        return f"Rechazo registrado. Respuesta: {result.get('message', 'OK')}"

    @function_tool
    async def programar_reintento(fecha_hora: str) -> str:
        """
        Llama cuando el cliente pide que lo llamen en otro momento.
        Args:
            fecha_hora: Fecha y hora preferida para el reintento (formato: YYYY-MM-DD HH:MM).
        """
        logger.info("[TOOL] programar_reintento → fecha_hora=%s", fecha_hora)
        result = await call_n8n_webhook(N8N_REINTENTO, {
            "id_cliente_wisphub": id_cliente,
            "fecha_hora": fecha_hora,
            "nombre": client_data.get("nombre"),
        })
        return f"Reintento agendado. Respuesta: {result.get('message', 'OK')}"

    @function_tool
    async def escalar_a_humano(motivo: str) -> str:
        """
        Llama cuando el cliente tiene una falla técnica urgente (sin internet hoy).
        Args:
            motivo: Tipo de escalamiento (ej: 'falla_tecnica', 'queja_grave').
        """
        logger.info("[TOOL] escalar_a_humano → motivo=%s", motivo)
        result = await call_n8n_webhook(N8N_ESCALAR, {
            "id_cliente_wisphub": id_cliente,
            "motivo": motivo,
            "nombre": client_data.get("nombre"),
        })
        return f"Escalado a humano. Respuesta: {result.get('message', 'OK')}"

    # ── Inicializar el modelo Gemini Live ────────────────────────────────────

    model = google.realtime.RealtimeModel(
        model="gemini-3.1-flash-live-preview",
        voice="Aoede",          # Gemini Live Voice (Flash Live)
        temperature=0.7,
        instructions=system_prompt,
    )

    # ── Crear la sesión del agente ────────────────────────────────────────────

    agent = google.realtime.RealtimeAgent(
        model=model,
        tools=[confirmar_upgrade, registrar_rechazo, programar_reintento, escalar_a_humano],
    )

    logger.info("[SESSION] Agente Sofía iniciado para cliente %s (Cat. %s)",
                client_data.get("nombre"), client_data.get("categoria"))

    # ── Iniciar sesión en el Room ─────────────────────────────────────────────
    await agent.start(ctx.room)

    # Sofía inicia la conversación con el pitch según la categoría
    # El saludo inicial se hace desde el system prompt, Gemini lo activará automáticamente
    # al detectar que el participante (cliente SIP) entró al room.


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def prewarm_process(proc: rtc.ProcessContext):
    """Verifica la conexión y configuración antes de aceptar llamadas."""
    logger.info("⚡ [BOOT] Agente de Voz Sofía INICIADO (Modo: %s)", "models/gemini-3.1-flash-live-preview")
    asyncio.create_task(heartbeat())
    logger.info("⚡ [BOOT] Esperando llamadas SIP de LiveKit...")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm_process,
            request_fnc=request_fnc,
        )
    )
