import csv
import io
import mimetypes
import uuid
from urllib import error, request

from django.http import HttpResponse
from django.shortcuts import render


API_URL = "https://bank-csv-extractor.jeefdata.com/"
CSV_SESSION_KEY = "latest_csv"
BANK_ENTITIES = [
	{"name": "BBVA", "prefix": "/bbva"},
]


def _build_multipart_body(files, field_name):
	boundary = f"----DjangoBoundary{uuid.uuid4().hex}"
	body = bytearray()

	for uploaded in files:
		content_type = uploaded.content_type or mimetypes.guess_type(uploaded.name)[0] or "application/pdf"
		body.extend(f"--{boundary}\r\n".encode("utf-8"))
		body.extend(
			(
				f'Content-Disposition: form-data; name="{field_name}"; '
				f'filename="{uploaded.name}"\r\n'
			).encode("utf-8")
		)
		body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
		body.extend(uploaded.read())
		body.extend(b"\r\n")

	body.extend(f"--{boundary}--\r\n".encode("utf-8"))
	return bytes(body), boundary


def _request_csv_from_api(files, api_endpoint):
	attempts = ["files", "file"]
	last_exception = None

	for field_name in attempts:
		for uploaded in files:
			uploaded.seek(0)

		body, boundary = _build_multipart_body(files, field_name)
		req = request.Request(
			api_endpoint,
			data=body,
			headers={
				"Content-Type": f"multipart/form-data; boundary={boundary}",
				"Accept": "text/csv,*/*",
			},
			method="POST",
		)

		try:
			with request.urlopen(req, timeout=180) as response:
				return response.read()
		except error.HTTPError as exc:
			# Try the alternate form field name for APIs with a different contract.
			if exc.code in (400, 404, 415, 422):
				last_exception = exc
				continue
			raise
		except error.URLError as exc:
			raise RuntimeError("No se pudo conectar con la API de extracción.") from exc

	if last_exception:
		raise RuntimeError(f"La API rechazó la solicitud: {last_exception.code} {last_exception.reason}")

	raise RuntimeError("No fue posible procesar la solicitud en la API.")


def _decode_csv_bytes(csv_bytes):
	for encoding in ("utf-8-sig", "utf-8", "latin-1"):
		try:
			return csv_bytes.decode(encoding)
		except UnicodeDecodeError:
			continue
	return csv_bytes.decode("utf-8", errors="replace")


def index(request):
	default_prefix = BANK_ENTITIES[0]["prefix"]
	context = {
		"api_url": API_URL,
		"bank_entities": BANK_ENTITIES,
		"selected_bank_prefix": default_prefix,
		"selected_api_endpoint": f"{API_URL.rstrip('/')}{default_prefix}",
		"csv_headers": [],
		"csv_rows": [],
		"error_message": "",
	}

	if request.method == "POST":
		selected_prefix = request.POST.get("bank_prefix", default_prefix)
		allowed_prefixes = {entity["prefix"] for entity in BANK_ENTITIES}
		if selected_prefix not in allowed_prefixes:
			selected_prefix = default_prefix

		api_endpoint = f"{API_URL.rstrip('/')}{selected_prefix}"
		context["selected_bank_prefix"] = selected_prefix
		context["selected_api_endpoint"] = api_endpoint

		uploaded_files = request.FILES.getlist("pdf_files")
		if not uploaded_files:
			context["error_message"] = "Selecciona al menos un PDF para procesar."
			return render(request, "web_ui/index.html", context)

		for uploaded in uploaded_files:
			if not uploaded.name.lower().endswith(".pdf"):
				context["error_message"] = "Todos los archivos deben tener formato PDF."
				return render(request, "web_ui/index.html", context)

		try:
			csv_bytes = _request_csv_from_api(uploaded_files, api_endpoint)
			csv_text = _decode_csv_bytes(csv_bytes)
		except Exception as exc:  # noqa: BLE001
			context["error_message"] = f"Error al procesar la extracción: {exc}"
			return render(request, "web_ui/index.html", context)

		request.session[CSV_SESSION_KEY] = csv_text
		rows = list(csv.reader(io.StringIO(csv_text)))
		if rows:
			context["csv_headers"] = rows[0]
			context["csv_rows"] = rows[1:51]
		else:
			context["error_message"] = "La API respondió pero el CSV llegó vacío."

	return render(request, "web_ui/index.html", context)


def download_csv(request):
	csv_text = request.session.get(CSV_SESSION_KEY, "")
	if not csv_text:
		return HttpResponse("No hay CSV para descargar todavía.", status=404)

	response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
	response["Content-Disposition"] = 'attachment; filename="extract_result.csv"'
	return response
