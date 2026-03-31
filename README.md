# Agente de Voz Sofía — Gemini Live + LiveKit

## Archivos

| Archivo | Propósito |
|---|---|
| `agent.py` | Agente principal. Escucha el Room de LiveKit, conecta a Gemini 3.1 Flash Live y maneja la conversación con Sofía |
| `caller.py` | Despachador de llamadas salientes. Usado por n8n para crear el Room y marcar el número del cliente via SIP |
| `requirements.txt` | Dependencias Python |
| `.env.example` | Plantilla de variables de entorno (copiar como `.env` y rellenar) |

## Setup Rápido (VPS)

```bash
# 1. Clonar o copiar esta carpeta al VPS
cd scripts/gemini_voice_agent

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus keys de Google, LiveKit y los IDs de SIP

# 4. Iniciar el agente (queda escuchando llamadas)
python agent.py start
```

## Prueba Manual de Llamada Saliente

```bash
python caller.py \
  --phone "+573001234567" \
  --room "test-upgrade-001" \
  --meta '{"nombre":"Juan Prueba","categoria":"A","velocidad_actual":30,"precio_actual":69900,"precio_actual_txt":"sesenta y nueve mil novecientos pesos","plan_upsell":"FAMILIA","precio_upsell":89900,"precio_upsell_txt":"ochenta y nueve mil novecientos pesos","velocidad_upsell":200,"velocidad_upsell_txt":"doscientas megas","plan_downsell":"HOGAR","precio_downsell":69900,"precio_downsell_txt":"sesenta y nueve mil novecientos pesos","velocidad_downsell":100,"velocidad_downsell_txt":"cien megas","diario_upsell_txt":"dos mil novecientos noventa y siete pesos","diario_downsell_txt":"dos mil trescientos treinta pesos","veces_upsell_txt":"el doble","veces_downsell_txt":"el doble","fecha_activacion":"el primero de mayo","id_cliente_wisphub":"12345"}'
```

## Flujo de Datos

```
n8n (lanza campaña)
  → caller.py --phone X --room Y --meta {...}
    → LiveKit: crea Room con metadatos del cliente
    → LiveKit SIP: marca el número via Issabel 4
      → Cliente contesta
        → agent.py detecta participante nuevo
          → Gemini 3.1 Flash Live: saluda según categoría
            → Cliente responde → Gemini maneja objeciones
              → Tool Call → n8n webhook → Supabase/WispHub
```

## Prerequisites LiveKit Cloud

1. Crear cuenta en https://cloud.livekit.io (FREE tier: 3,000 participantes/mes)
2. Crear proyecto → copiar `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
3. En **Telephony → SIP Trunks → Outbound**: crear troncal apuntando al host de Issabel 4
4. Copiar el `SIP_OUTBOUND_TRUNK_ID` (empieza con `ST_`)
