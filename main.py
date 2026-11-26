from datetime import datetime, timedelta, timezone
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import requests

URL_PROGRAMACION = "https://trivisioncr.com/programacion/"
TZ_CR = timezone(timedelta(hours=-6))
CHANNEL_ID = "trivision.cr"
CHANNEL_NAME = "Trivisión"
ARCHIVO_SALIDA = "epg_trivision_diario.xml"

DIAS_SEMANA = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]


def normalizar_texto(texto: str) -> str:
    """Convierte a minúsculas y elimina tildes para evitar fallos de coincidencia."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto.strip().lower())
        if unicodedata.category(c) != "Mn"
    )


def obtener_parrilla_trivision() -> list[dict]:
    """Extrae la programación del día actual desde el objeto JS tvProgramacion."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(URL_PROGRAMACION, headers=headers, timeout=20)
    resp.raise_for_status()

    match_obj = re.search(
        r"(?:const|let|var)\s+tvProgramacion\s*=\s*(\{.*?\});",
        resp.text,
        re.DOTALL,
    )
    if not match_obj:
        print("[Error] No se encontró el objeto 'tvProgramacion' en el HTML.")
        return []

    bloques = re.findall(
        r"([A-Za-zÁÉÍÓÚáéíóúÑñ]+)\s*:\s*\[(.*?)\]",
        match_obj.group(1),
        re.DOTALL,
    )
    parrilla_por_dia = {normalizar_texto(dia): contenido for dia, contenido in bloques}

    hoy = datetime.now(TZ_CR).replace(hour=0, minute=0, second=0, microsecond=0)
    dia_actual = DIAS_SEMANA[hoy.weekday()]
    clave_dia = normalizar_texto(dia_actual)

    bloque_hoy = parrilla_por_dia.get(clave_dia)
    if not bloque_hoy:
        print(f"[Error] No se encontró programación para el día '{dia_actual}'.")
        return []

    patron_item = re.compile(
        r'hora\s*:\s*["\'](\d{1,2}:\d{2})["\']\s*,\s*'
        r"duracion\s*:\s*(\d+)\s*,\s*"
        r'programa\s*:\s*(["\'])(.*?)\3',
        re.DOTALL,
    )

    programas_crudos = []
    for hora_str, duracion_str, _, titulo in patron_item.findall(bloque_hoy):
        hora, minuto = map(int, hora_str.split(":"))
        duracion_min = int(duracion_str)
        titulo_limpio = re.sub(r"\s+", " ", titulo).strip()

        if 0 <= hora <= 23 and 0 <= minuto <= 59 and duracion_min > 0 and titulo_limpio:
            programas_crudos.append(
                {
                    "hora": hora,
                    "minuto": minuto,
                    "duracion": duracion_min,
                    "programa": titulo_limpio,
                }
            )

    programas_crudos.sort(key=lambda x: (x["hora"], x["minuto"]))

    resultado = []
    for item in programas_crudos:
        dt_inicio = hoy.replace(hour=item["hora"], minute=item["minuto"])
        dt_fin = dt_inicio + timedelta(minutes=item["duracion"])

        resultado.append(
            {
                "channel_id": CHANNEL_ID,
                "programa": item["programa"],
                "inicio_xmltv": dt_inicio.strftime("%Y%m%d%H%M%S %z"),
                "fin_xmltv": dt_fin.strftime("%Y%m%d%H%M%S %z"),
            }
        )

    return resultado


def guardar_xmltv(programas: list[dict], ruta_archivo: str = ARCHIVO_SALIDA) -> None:
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "Trivision-Daily-EPG",
            "source-info-url": URL_PROGRAMACION,
        },
    )

    canal = ET.SubElement(tv, "channel", {"id": CHANNEL_ID})
    display = ET.SubElement(canal, "display-name", {"lang": "es"})
    display.text = CHANNEL_NAME

    for item in programas:
        prog = ET.SubElement(
            tv,
            "programme",
            {
                "start": item["inicio_xmltv"],
                "stop": item["fin_xmltv"],
                "channel": item["channel_id"],
            },
        )
        title = ET.SubElement(prog, "title", {"lang": "es"})
        title.text = item["programa"]

    if hasattr(ET, "indent"):
        ET.indent(tv, space="  ")

    tree = ET.ElementTree(tv)
    tree.write(ruta_archivo, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    print("Obteniendo programación diaria de Trivisión...")
    parrilla = obtener_parrilla_trivision()
    if not parrilla:
        print("No se pudo generar el EPG. Revisa la estructura de la web.")
        sys.exit(1)

    guardar_xmltv(parrilla, ARCHIVO_SALIDA)
    print(f"EPG generado con {len(parrilla)} programas en '{ARCHIVO_SALIDA}'.")
