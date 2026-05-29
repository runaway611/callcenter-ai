from fastapi import FastAPI, UploadFile, File, Form
from faster_whisper import WhisperModel
import tempfile
import os
import json
import re
import requests
import logging
import time
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
app = FastAPI(title="CallCenter AI - Audio Processor")
 
print("Cargando modelo Whisper...")
model = WhisperModel("medium", device="cpu", compute_type="int8")
print("Whisper listo.")
 
# ─── Constantes ───────────────────────────────────────────────────────────────
 
OLLAMA_URL     = os.getenv("OLLAMA_HOST", "http://ollama:11434") + "/api/generate"
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_RETRIES = int(os.getenv("OLLAMA_RETRIES", "3"))
 
ANALYSIS_DEFAULT = {
    "sentimiento_cliente": "neutro",
    "cliente_interesado":  False,
    "tipo_llamada":        "desconocido",
    "riesgo":              "medio",
    "score_asesor":        0,
    "fortalezas":          [],
    "mejoras":             [],
    "resumen":             "No se pudo analizar la llamada.",
}
 
# ─── Rutas ────────────────────────────────────────────────────────────────────
 
@app.get("/")
def root():
    return {"status": "ok", "service": "fastapi-audio-processor"}
 
@app.get("/health")
def health():
    ollama_ok = _check_ollama()
    return {
        "status":       "healthy",
        "whisper":      "ready",
        "ollama":       "reachable" if ollama_ok else "unreachable",
        "ollama_model": OLLAMA_MODEL,
    }
 
@app.post("/process-audio")
async def process_audio(
    audio:     UploadFile = File(...),
    call_id:   str        = Form(...),
    tenant_id: str        = Form(...),
):
    suffix = os.path.splitext(audio.filename or "")[1] or ".wav"
 
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
 
    try:
        # ── Transcripción ──────────────────────────────────────────────────
        segments_iter, info = model.transcribe(
            tmp_path,
            beam_size=5,
            language="es",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
 
        transcription = ""
        segments_list = []
        for seg in segments_iter:
            transcription += seg.text + " "
            segments_list.append({
                "start": round(seg.start, 2),
                "end":   round(seg.end, 2),
                "text":  seg.text.strip(),
            })
 
        transcription = transcription.strip()
 
        # ── Análisis ───────────────────────────────────────────────────────
        analysis, analysis_error = analyze_with_ollama(transcription)
 
        return {
            "call_id":        call_id,
            "tenant_id":      tenant_id,
            "transcription":  transcription,
            "segments":       segments_list,
            "language":       info.language,
            "language_prob":  round(info.language_probability, 3),
            "analysis":       analysis,
            "analysis_error": analysis_error,
        }
 
    finally:
        os.unlink(tmp_path)
 
# ─── Ollama ───────────────────────────────────────────────────────────────────
 
def _check_ollama() -> bool:
    try:
        r = requests.get(
            os.getenv("OLLAMA_HOST", "http://ollama:11434"),
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False
 
 
def _extract_json(text: str) -> dict:
    """
    Extrae el primer bloque JSON válido de un texto que puede contener
    prosa, bloques ```json ... ``` u otras decoraciones.
    """
    # 1. Intento directo
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
 
    # 2. Bloque ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
 
    # 3. Primera llave { ... } del texto
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
 
    raise ValueError(f"No se encontró JSON válido en la respuesta:\n{text[:300]}")
 
 
def analyze_with_ollama(transcription: str) -> tuple:
    """
    Devuelve (analysis_dict, error_str).
    error_str es None si el análisis fue exitoso.
    """
    if not transcription:
        return {**ANALYSIS_DEFAULT, "resumen": "Transcripción vacía."}, "empty_transcription"
 
    prompt = f"""Eres un analista experto de calidad de callcenter en Colombia.
Analiza esta transcripción y responde ÚNICAMENTE con un objeto JSON válido.
No incluyas texto antes ni después del JSON. No uses bloques de código markdown.
 
TRANSCRIPCIÓN:
{transcription}
 
Responde exactamente con este JSON (sin comentarios, sin texto adicional):
{{
  "sentimiento_cliente": "positivo|negativo|neutro",
  "cliente_interesado": true,
  "tipo_llamada": "venta|soporte|queja|informacion",
  "riesgo": "alto|medio|bajo",
  "score_asesor": 75,
  "fortalezas": ["punto 1", "punto 2"],
  "mejoras": ["punto 1", "punto 2"],
  "resumen": "resumen breve de la llamada"
}}"""
 
    last_error = "unknown"
 
    for attempt in range(1, OLLAMA_RETRIES + 1):
        try:
            logger.info(f"Ollama intento {attempt}/{OLLAMA_RETRIES}")
 
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model":  OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",       # fuerza JSON nativo en Ollama >= 0.1.9
                    "options": {
                        "temperature": 0.1, # respuestas más deterministas
                        "num_predict": 512,
                    },
                },
                timeout=OLLAMA_TIMEOUT,
            )
            response.raise_for_status()
 
            raw = response.json().get("response", "")
            logger.info(f"Respuesta Ollama (primeros 200 chars): {raw[:200]}")
 
            parsed = _extract_json(raw)
 
            # Merge con defaults para campos faltantes
            result = {**ANALYSIS_DEFAULT, **parsed}
 
            # Sanitizar score_asesor
            try:
                result["score_asesor"] = max(0, min(100, int(result["score_asesor"])))
            except (ValueError, TypeError):
                result["score_asesor"] = 0
 
            return result, None
 
        except requests.exceptions.Timeout:
            last_error = f"timeout en intento {attempt} ({OLLAMA_TIMEOUT}s)"
            logger.warning(last_error)
 
        except requests.exceptions.ConnectionError:
            last_error = f"Ollama no disponible (intento {attempt})"
            logger.warning(last_error)
            time.sleep(2)
 
        except requests.exceptions.HTTPError as e:
            last_error = f"HTTP error: {e}"
            logger.error(last_error)
            break
 
        except ValueError as e:
            last_error = f"JSON invalido en intento {attempt}: {e}"
            logger.warning(last_error)
 
        except Exception as e:
            last_error = f"Error inesperado: {e}"
            logger.exception(last_error)
            break
 
    logger.error(f"Analisis fallo tras {OLLAMA_RETRIES} intentos: {last_error}")
    return {**ANALYSIS_DEFAULT, "resumen": f"Error al analizar: {last_error}"}, last_error
