from fastapi import FastAPI, UploadFile, File, Form
from faster_whisper import WhisperModel
import tempfile
import os
import json
import requests

app = FastAPI(title="CallCenter AI - Audio Processor")

print("Cargando modelo Whisper...")
model = WhisperModel("medium", device="cpu", compute_type="int8")
print("Whisper listo.")


@app.get("/")
def root():
    return {"status": "ok", "service": "fastapi-audio-processor"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/process-audio")
async def process_audio(
    audio: UploadFile = File(...),
    call_id: str = Form(...),
    tenant_id: str = Form(...),
):
    suffix = os.path.splitext(audio.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        segments, info = model.transcribe(
            tmp_path,
            beam_size=5,
            language="es",
        )

        transcription = ""
        segments_list = []
        for segment in segments:
            transcription += segment.text + "\n"
            segments_list.append({
                "start": round(segment.start, 2),
                "end":   round(segment.end, 2),
                "text":  segment.text.strip(),
            })

        analysis = analyze_with_ollama(transcription)

        return {
            "call_id":       call_id,
            "tenant_id":     tenant_id,
            "transcription": transcription.strip(),
            "segments":      segments_list,
            "analysis":      analysis,
            "language":      info.language,
        }

    finally:
        os.unlink(tmp_path)

def analyze_with_ollama(transcription: str) -> dict:
    prompt = f"""Eres un analista experto de calidad de callcenter en Colombia.
Analiza esta transcripción y responde SOLO con JSON válido, sin texto adicional.

TRANSCRIPCIÓN:
{transcription}

Responde exactamente con este formato JSON:
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

    try:
        response = requests.post(
            "http://ollama:11434/api/generate",
            json={
                "model":  "llama3.2:3b",
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        raw = response.json()["response"]
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        return {
            "error":               str(e),
            "sentimiento_cliente": "neutro",
            "cliente_interesado":  False,
            "tipo_llamada":        "desconocido",
            "riesgo":              "medio",
            "score_asesor":        0,
            "fortalezas":          [],
            "mejoras":             [],
            "resumen":             "Error al analizar la llamada.",
        }
