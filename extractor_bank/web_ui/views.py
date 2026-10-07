import csv
import io
import uuid
from urllib import error, request as urlrequest

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

API_URL = "https://bank-csv-extractor.jeefdata.com"
FIELD_NAME = "archivo"
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
BANK_ENTITIES = [
    {"name": "BBVA", "prefix": "/bbva/procesar"},
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def _multipart(name, filename, data):
    boundary = f"----Django{uuid.uuid4().hex}"
    safe_name = filename.replace('"', "'")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{FIELD_NAME}"; filename="{safe_name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, boundary


def _call_api(endpoint, filename, data):
    body, boundary = _multipart(FIELD_NAME, filename, data)
    req = urlrequest.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "text/csv,*/*",
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


def index(request):
    return render(request, "web_ui/index.html", {"bank_entities": BANK_ENTITIES})


@require_POST
def process_pdf(request):
    """Procesa UN pdf y devuelve {csv, rows} en JSON."""
    prefix = request.POST.get("bank_prefix", "")
    if prefix not in {e["prefix"] for e in BANK_ENTITIES}:
        return JsonResponse({"error": "Entidad bancaria no válida."}, status=400)

    pdf = request.FILES.get("pdf_file")
    if not pdf:
        return JsonResponse({"error": "No se recibió ningún archivo."}, status=400)
    if pdf.size > MAX_PDF_BYTES:
        return JsonResponse({"error": "El PDF supera los 20 MB."}, status=400)

    data = pdf.read()
    if not data.startswith(b"%PDF"):
        return JsonResponse({"error": "El archivo no es un PDF válido."}, status=400)

    try:
        text = _decode(_call_api(f"{API_URL}{prefix}", pdf.name, data))
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return JsonResponse({"error": "La API no devolvió transacciones para este PDF."}, status=422)

    return JsonResponse({"csv": text, "rows": len(rows) - 1})