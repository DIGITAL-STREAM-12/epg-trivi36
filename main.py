from datetime import datetime, timedelta, timezone
import re
from typing import Optional
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import requests

URL_PROGRAMACION = "https://trivisioncr.com/programacion/"
TZ_CR = timezone(timedelta(hours=-6))
CHANNEL_ID = "trivision.cr"
CHANNEL_NAME = "Trivisión"

# Patrón flexible para hora de 24h (ej: 18:00) o 12h (ej: 6:00 pm, 6:00 a.m.)
PATRON_HORA = re.compile(
    r"\b(\d{1,2}:\d{2})\s*(am|pm|a\.m\.|p\.m\.|m|md)?\b", re.IGNORECASE
)


def parsear_hora_24h(texto_hora: str) -> Optional[tuple[int, int]]:
    """Convierte texto de hora a formato (hora_24, minuto)."""
    m = PATRON_HORA.search(texto_hora.strip())
    if not m:
        return None

    hh_mm = m.group(1)
    periodo = (m.group(2) or "").lower().replace(".", "")
    hora, minuto = map(int, hh_mm.split(":"))

    if not periodo:
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return (hora, minuto)
        return None

    if periodo in ("m", "md"):
        hora_24 = 12 if hora == 12 else hora
    elif periodo == "am":
        hora_24 = 0 if hora == 12 else hora
    else:  # pm
        hora_24 = hora if hora == 12 else hora + 12

    if 0 <= hora_24 <= 23 and 0 <= minuto <= 59:
        return (hora_24, minuto)
    return None


def obtener_parrilla_trivision() -> list[dict]:
    """Extrae la programación desde la web de Trivisión de forma robusta."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(URL_PROGRAMACION, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Acotamos la búsqueda a contenedores de texto principales para evitar duplicados masivos en divs anidados
    candidatos_elementos = soup.find_all(["p", "li", "td", "h3", "h4", "strong"])
    
    programas_crudos = []
    vistos = set()

    for el in candidatos_elementos:
        texto = el.get_text(strip=True)
        if not texto:
            continue
            
        match_hora = PATRON_HORA.search(texto)
        if match_hora:
            hora_extraida = match_hora.group(0)
            tiempo_parsed = parsear_hora_24h(hora_extraida)
            
            if tiempo_parsed:
                titulo = texto.replace(hora_extraida, "").strip("-:– \t\n")
                
                # Si el bloque solo contenía la hora, buscamos en el siguiente hermano
                if len(titulo) < 3:
                    siguiente = el.find_next_sibling()
                    if siguiente:
                        titulo = siguiente.get_text(strip=True)
                
                if titulo and len(titulo) >= 2:
                    clave = (tiempo_parsed, titulo.lower())
                    if clave not in vistos:
                        vistos.add(clave)
                        programas_crudos.append({
                            "inicio_24": tiempo_parsed,
                            "programa": titulo
                        })

    # Respaldo basado en líneas de texto si el filtrado anterior no encuentra suficientes
    if not programas_crudos:
        main = soup.find("main") or soup.body or soup
        lineas = [re.sub(r"\s+", " ", txt).strip() for txt in main.stripped_strings if re.sub(r"\s+", " ", txt).strip()]
        for i, linea in enumerate(lineas):
            inicio = parsear_hora_24h(linea)
            if inicio:
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
                        programas_crudos.append({"inicio_24": inicio, "programa": titulo})

    # Ordenar estrictamente por hora y minuto cronológico
    programas_crudos.sort(key=lambda x: (x["inicio_24"][0], x["inicio_24"][1]))

    if not programas_crudos:
        print("[Aviso] No se detectaron programas automáticamente en el HTML.")
        return []

    # Generar la parrilla para los próximos 7 días con cálculo correcto de horas de fin
    hoy = datetime.now(TZ_CR).replace(hour=0, minute=0, second=0, microsecond=0)
    resultado = []

    for dia_idx in range(7):
        fecha_base = hoy + timedelta(days=dia_idx)
        
        for idx, item in enumerate(programas_crudos):
            h_ini, m_ini = item["inicio_24"]
            dt_inicio = fecha_base.replace(hour=h_ini, minute=m_ini)

            # Determinar hora de fin basada en el siguiente programa del día
            if idx + 1 < len(programas_crudos):
                h_sig, m_sig = programas_crudos[idx + 1]["inicio_24"]
                dt_fin = fecha_base.replace(hour=h_sig, minute=m_sig)
                if dt_fin <= dt_inicio:
                    dt_fin += timedelta(days=1)
            else:
                # Si es el último programa del día, asume que termina a la medianoche o dura 1 hora por defecto
                dt_fin = dt_inicio + timedelta(hours=1)

            resultado.append({
                "channel_id": CHANNEL_ID,
                "programa": item["programa"],
                "inicio_iso": dt_inicio.isoformat(),
                "fin_iso": dt_fin.isoformat(),
                "inicio_xmltv": dt_inicio.strftime("%Y%m%d%H%M%S %z"),
                "fin_xmltv": dt_fin.strftime("%Y%m%d%H%M%S %z"),
            })

    return resultado


def guardar_xmltv(programas: list[dict], ruta_archivo: str = "epg_trivision_semanal.xml") -> None:
    tv = ET.Element("tv", {
        "generator-info-name": "Trivision-Weekly-EPG",
        "source-info-url": URL_PROGRAMACION
    })

    canal = ET.SubElement(tv, "channel", {"id": CHANNEL_ID})
    display = ET.SubElement(canal, "display-name", {"lang": "es"})
    display.text = CHANNEL_NAME

    for item in programas:
        prog = ET.SubElement(tv, "programme", {
            "start": item["inicio_xmltv"],
            "stop": item["fin_xmltv"],
            "channel": CHANNEL_ID
        })
        title = ET.SubElement(prog, "title", {"lang": "es"})
        title.text = item["programa"]

    # Compatibilidad segura para ET.indent en versiones antiguas de Python
    if hasattr(ET, "indent"):
        ET.indent(tv, space=" ")

    tree = ET.ElementTree(tv)
    tree.write(ruta_archivo, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    print("Obteniendo programación de Trivisión...")
    parrilla = obtener_parrilla_trivision()
    if parrilla:
        guardar_xmltv(parrilla, "epg_trivision_semanal.xml")
        print(f"¡Éxito! EPG generado con {len(parrilla)} programas en 'epg_trivision_semanal.xml'.")
    else:
        print("No se pudo generar el EPG. Comprueba la estructura de la web.")
