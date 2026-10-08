import csv
import io
import json
import uuid
from urllib import error, request as urlrequest

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

API_URL = "https://bank-csv-extractor.jeefdata.com"
FIELD_NAME = "archivo"
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
# Cada banco expone /<slug>/procesar y /<slug>/renombrar
BANK_ENTITIES = [
    {"name": "BBVA", "slug": "bbva"},
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


# ---------- Helpers compartidos ----------

def _multipart(filename, data):
    boundary = f"----Django{uuid.uuid4().hex}"
    safe_name = filename.replace('"', "'")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{FIELD_NAME}"; filename="{safe_name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, boundary


def _call_api(slug, action, filename, data):
    body, boundary = _multipart(filename, data)
    req = urlrequest.Request(
        f"{API_URL}/{slug}/{action}",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json,text/csv,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=180) as resp:
            return resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"La API respondió {exc.code} {exc.reason}. {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError("No se pudo conectar con la API de extracción.") from exc


def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _get_upload(request):
    """Valida banco + PDF. Devuelve (slug, nombre, bytes) o lanza ValueError."""
    slug = request.POST.get("bank", "")
    if slug not in {e["slug"] for e in BANK_ENTITIES}:
        raise ValueError("Entidad bancaria no válida.")
    pdf = request.FILES.get("pdf_file")
    if not pdf:
        raise ValueError("No se recibió ningún archivo.")
    if pdf.size > MAX_PDF_BYTES:
        raise ValueError("El PDF supera los 20 MB.")
    data = pdf.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("El archivo no es un PDF válido.")
    return slug, pdf.name, data


# ---------- Extractor ----------

def index(request):
    return render(request, "web_ui/index.html", {"bank_entities": BANK_ENTITIES})


@require_POST
def process_pdf(request):
    """Procesa UN pdf y devuelve {csv, rows}."""
    try:
        slug, name, data = _get_upload(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        text = _decode(_call_api(slug, "procesar", name, data))
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return JsonResponse({"error": "La API no devolvió transacciones para este PDF."}, status=422)
    return JsonResponse({"csv": text, "rows": len(rows) - 1})


# ---------- Renombrar ----------

def rename_page(request):
    return render(request, "web_ui/renombrar.html", {"bank_entities": BANK_ENTITIES})


@require_POST
def rename_pdf(request):
    """Envía UN pdf a /<banco>/renombrar y devuelve {nombre_original, resultado}."""
    try:
        slug, name, data = _get_upload(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        raw = _call_api(slug, "renombrar", name, data)
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    try:
        payload = json.loads(_decode(raw))
    except ValueError:
        return JsonResponse({"error": "La API no devolvió un JSON válido."}, status=502)

    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    resultado = payload.get("resultado") if isinstance(payload, dict) else None
    if not isinstance(resultado, str) or not resultado.strip():
        return JsonResponse({"error": "No se pudo determinar el nuevo nombre."}, status=422)

    return JsonResponse({
        "nombre_original": payload.get("nombre_original", name),
        "resultado": resultado.strip(),
    })