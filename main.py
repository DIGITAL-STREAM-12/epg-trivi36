from datetime import datetime, timedelta, timezone
import json
import re
from typing import Optional
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import requests

URL_PROGRAMACION = "https://trivisioncr.com/programacion/"

TZ_CR = timezone(timedelta(hours=-6))
CHANNEL_ID = "trivision.cr"
CHANNEL_NAME = "Trivisión"

PATRON_HORA = re.compile(
    r"\b(\d{1,2}:\d{2})\s*(am|pm|a\.m\.|p\.m\.|m|md)?\b", re.IGNORECASE
)


def parsear_hora_24h(texto_hora: str) -> Optional[tuple[int, int]]:
    """Convierte horas en texto a formato (hora_24, minuto)."""
    m = PATRON_HORA.search(texto_hora.strip())
    if not m:
        return None

    hh_mm = m.group(1)
    periodo = (m.group(2) or "").lower().replace(".", "")
    hora, minuto = map(int, hh_mm.split(":"))

    if not periodo:
        return (hora, minuto)

    if periodo in ("m", "md"):
        hora_24 = 12 if hora == 12 else hora
    elif periodo == "am":
        hora_24 = 0 if hora == 12 else hora
    else:  # pm
        hora_24 = hora if hora == 12 else hora + 12

    return (hora_24, minuto)


def obtener_parrilla_trivision() -> list[dict]:
    """Extrae la programación desde la web de Trivisión."""
    resp = requests.get(
        URL_PROGRAMACION,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TrivisionEPGBot/1.0)"},
        timeout=20,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    main = soup.find("main") or soup.body or soup

    lineas = [
        re.sub(r"\s+", " ", txt).strip()
        for txt in main.stripped_strings
        if re.sub(r"\s+", " ", txt).strip()
    ]

    programas = []
    vistos = set()
    hoy = datetime.now(TZ_CR).replace(hour=0, minute=0, second=0, microsecond=0)

    # Lógica de extracción adaptada para leer bloques de hora y título
    for i, linea in enumerate(lineas):
        inicio = parsear_hora_24h(linea)
        if inicio:
            # Buscar el título del programa cercano
            titulo = None
            for offset in range(1, 4):
                if i + offset < len(lineas):
                    candidato = lineas[i + offset]
                    if not PATRON_HORA.search(candidato):
                        titulo = candidato
                        break
            
            if titulo:
                clave = (inicio, titulo.lower())
                if clave not in vistos:
                    vistos.add(clave)
                    programas.append(
                        {
                            "inicio_24": inicio,
                            "programa": titulo,
                        }
                    )

    programas.sort(key=lambda item: item["inicio_24"])

    # Generamos la programación para los próximos 7 días basada en la plantilla extraída
    resultado = []
    for dia_idx in range(7):
        fecha_base = hoy + timedelta(days=dia_idx)
        
        for idx, item in enumerate(programas):
            h_ini, m_ini = item["inicio_24"]
            dt_inicio = fecha_base.replace(hour=h_ini, minute=m_ini)

            if idx + 1 < len(programas):
                h_sig, m_sig = programas[idx + 1]["inicio_24"]
                dt_fin = fecha_base.replace(hour=h_sig, minute=m_sig)
                if dt_fin <= dt_inicio:
                    dt_fin += timedelta(days=1)
            else:
                dt_fin = (fecha_base + timedelta(days=1)).replace(hour=0, minute=0)

            resultado.append(
                {
                    "channel_id": CHANNEL_ID,
                    "programa": item["programa"],
                    "inicio_iso": dt_inicio.isoformat(),
                    "fin_iso": dt_fin.isoformat(),
                    "inicio_xmltv": dt_inicio.strftime("%Y%m%d%H%M%S %z"),
                    "fin_xmltv": dt_fin.strftime("%Y%m%d%H%M%S %z"),
                }
            )

    return resultado


def guardar_json_semanal(programas: list[dict], ruta_archivo: str) -> None:
    payload = {
        "canal": CHANNEL_NAME,
        "channel_id": CHANNEL_ID,
        "generado_en": datetime.now(TZ_CR).isoformat(),
        "total_programas": len(programas),
        "programacion": programas,
    }
    with open(ruta_archivo, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def guardar_xmltv_semanal(programas: list[dict], ruta_archivo: str) -> None:
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": "Trivision-Weekly-EPG",
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
                "channel": CHANNEL_ID,
            },
        )
        title = ET.SubElement(prog, "title", {"lang": "es"})
        title.text = item["programa"]

    ET.indent(tv, space=" ")
    tree = ET.ElementTree(tv)
    tree.write(ruta_archivo, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    parrilla_semana = obtener_parrilla_trivision()
    guardar_xmltv_semanal(parrilla_semana, "epg_trivision_semanal.xml")
    guardar_json_semanal(parrilla_semana, "epg_trivision_semanal.json")
    print(
        f"Generado EPG semanal de Trivisión con {len(parrilla_semana)} programas en epg_trivision_semanal.xml"
    )
