"""
Corre cada 2 horas via GitHub Actions.
1. Lee todos los usuarios anotados en Supabase (con su rubro, nivel de
   experiencia, idiomas, modalidad y pais).
2. Lee ofertas de portales de empleo publicos (RSS + JSON), UNA sola vez por
   corrida (no una vez por usuario), para no sobrecargar ningun servicio.
3. Matchea con las palabras clave/skills/rubro de cada usuario y, si eligio
   un nivel de experiencia especifico (junior, semi senior, senior,
   gerencial), filtra tambien por eso. Si eligio "cualquiera", no filtra
   por nivel: sirve para cualquier persona, seniority y rubro.
4. Arma un resumen de perfil (nivel, idiomas -> regiones con alcance) y lo
   incluye arriba de cada mail.
5. Manda un mail (via Brevo) con las nuevas ofertas a cada usuario.
6. Registra lo ya enviado para no repetir avisos.
"""
import os
import html as html_lib
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BREVO_API_KEY = os.environ["BREVO_API_KEY"]
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "alertas@example.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "Alertas de Empleo")
SITE_URL = "https://kxl100rx.github.io/trabajaya/"
TRACKER_URL = SITE_URL + "recursos/tracker-busqueda-laboral.xlsx"
# Mail al que llegan las bajas y los reportes de ofertas rotas (mailto en el pie de cada mail).
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", SENDER_EMAIL)
MAX_JOBS_PER_MAIL = 15

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}
REQUEST_HEADERS = {"User-Agent": "alertas-empleo-bot/1.0 (+github actions, uso personal)"}

# Cada feed se pide UNA sola vez por corrida del robot (cada 2hs), sin
# importar cuantos usuarios haya, para no golpear ningun portal con
# pedidos repetidos. "lang" es el idioma predominante de esa fuente.
# Son feeds generales (todo rubro y todo nivel), no solo tech ni solo junior.
RSS_FEEDS = [
    {"url": "https://weworkremotely.com/categories/remote-programming-jobs.rss", "lang": "en"},
    {"url": "https://weworkremotely.com/categories/remote-design-jobs.rss", "lang": "en"},
    {"url": "https://weworkremotely.com/categories/remote-marketing-jobs.rss", "lang": "en"},
    {"url": "https://weworkremotely.com/categories/remote-customer-support-jobs.rss", "lang": "en"},
    {"url": "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss", "lang": "en"},
    {"url": "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss", "lang": "en"},
    # Remotive, RemoteOK, Working Nomads y Arbeitnow dieron de baja sus RSS
    # (404/410/HTML el 14/09/2026): ahora se leen por sus APIs JSON, ver JSON_FEEDS.
]

JSON_FEEDS = [
    {"url": "https://himalayas.app/jobs/api", "lang": "en", "kind": "himalayas"},
    {"url": "https://jobicy.com/api/v2/remote-jobs?count=50", "lang": "en", "kind": "jobicy"},
    {"url": "https://remotive.com/api/remote-jobs", "lang": "en", "kind": "remotive"},
    {"url": "https://remoteok.com/api", "lang": "en", "kind": "remoteok"},
    {"url": "https://www.workingnomads.com/api/exposed_jobs/", "lang": "en", "kind": "workingnomads"},
    {"url": "https://www.arbeitnow.com/api/job-board-api", "lang": "en", "kind": "arbeitnow"},
    # API pública, gratuita, sin key ni rate limit. Cubre LATAM (incluye
    # Argentina) con avisos remotos, hibridos Y PRESENCIALES -- es la
    # unica fuente que hoy nos da ofertas presenciales reales, no solo
    # remotas. Trae localidad (address_locality/address_country) que
    # usamos para filtrar por cercania cuando el usuario cargo su ciudad.
    {"url": "https://vacantesdigitales.com/api/list", "lang": "es", "kind": "vacantesdigitales"},
]

# Terminos que ayudan a reconocer el nivel de experiencia de un aviso.
# Solo se usan si el usuario eligio un nivel especifico (no "cualquiera").
SENIORITY_TERMS = {
    "junior": [
        "junior", "trainee", "entry level", "entry-level", "sin experiencia",
        "becario", "beca", "primer empleo", "graduate", "asistente", "aprendiz",
    ],
    "semi_senior": [
        "semi senior", "semi-senior", "ssr.", " ssr ", "mid level", "mid-level",
        "intermedio", "intermediate",
    ],
    "senior": [
        "senior", " sr.", " sr ", "lead", "principal", "staff",
    ],
    "gerencial": [
        "gerente", "manager", "director", "head of", "jefe", "chief", "vp ", "vicepresidente",
    ],
}

SENIORITY_LABEL = {
    "cualquiera": "cualquier nivel de experiencia",
    "junior": "Junior / Trainee",
    "semi_senior": "Semi Senior",
    "senior": "Senior",
    "gerencial": "Gerencial / Directivo",
}

LANG_REGIONS = {
    "es": "España y toda Latinoamerica",
    "en": "practicamente todo el mundo (USA, UK, Canada, Australia, Europa, India y mas)",
    "pt": "Brasil y Portugal",
    "fr": "Francia, Belgica, Canada (Quebec) y Africa francofona",
    "de": "Alemania, Austria y Suiza",
    "it": "Italia",
}

WORK_MODE_LABEL = {
    "remoto_mundial": "remoto, sin importar el pais",
    "remoto_pais": "remoto dentro de tu pais",
    "hibrido": "hibrido (remoto + presencial) en tu pais",
    "presencial": "presencial en tu pais",
    "cualquiera": "remoto o presencial, sin restriccion",
}


# ---------------------------------------------------------------------
# Kit de Búsqueda Laboral: cadenas de búsqueda + deep-links a portales
# que no podemos integrar (LinkedIn, Indeed, Computrabajo, etc). Misma
# lógica que el generador del formulario (index.html), portada a Python
# para poder mandarla por mail una sola vez, apenas alguien se anota.
# ---------------------------------------------------------------------
ROLE_MAP_BASE = {
    "Programación / IT": ["Desarrollador/a", "Analista de Sistemas"],
    "Ventas": ["Ejecutivo/a de Ventas", "Account Executive"],
    "Marketing": ["Analista de Marketing Digital"],
    "Datos": ["Data Analyst"],
    "Finanzas": ["Analista Financiero"],
    "Recursos Humanos": ["Analista de RRHH"],
    "Administración": ["Analista Administrativo/a"],
    "Salud": ["Profesional de la salud"],
    "Ingeniería": ["Ingeniero/a de Proyecto"],
    "Diseño": ["Diseñador/a UI/UX"],
    "Logística": ["Analista de Logística / Supply Chain"],
    "Legal": ["Asistente Legal / Paralegal"],
}

COUNTRY_CODE_MAP = {
    "argentina": "ar", "méxico": "mx", "mexico": "mx", "chile": "cl", "colombia": "co",
    "perú": "pe", "peru": "pe", "ecuador": "ec", "uruguay": "uy", "paraguay": "py",
    "bolivia": "bo", "venezuela": "ve", "panamá": "pa", "panama": "pa", "guatemala": "gt",
    "honduras": "hn", "el salvador": "sv", "nicaragua": "ni", "costa rica": "cr",
    "república dominicana": "do", "republica dominicana": "do", "puerto rico": "pr",
    "españa": "es", "spain": "es", "estados unidos": "us", "usa": "us", "united states": "us",
    "brasil": "br", "brazil": "br",
}
INDEED_DOMAINS = {"ar": "ar.indeed.com", "mx": "mx.indeed.com", "cl": "cl.indeed.com", "co": "co.indeed.com", "pe": "pe.indeed.com", "ec": "ec.indeed.com", "es": "es.indeed.com", "us": "www.indeed.com", "uy": "uy.indeed.com"}
COMPUTRABAJO_DOMAINS = {"ar": "ar.computrabajo.com", "mx": "mx.computrabajo.com", "co": "co.computrabajo.com", "cl": "cl.computrabajo.com", "pe": "pe.computrabajo.com", "ec": "ec.computrabajo.com"}
BUMERAN_DOMAINS = {"ar": "www.bumeran.com.ar", "mx": "www.bumeran.com.mx", "pe": "www.bumeran.com.pe"}


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def detectar_codigo_pais(pais):
    if not pais:
        return None
    t = pais.strip().lower()
    for name, code in COUNTRY_CODE_MAP.items():
        if name in t:
            return code
    return None


def generar_palabras_simples(areas, skills):
    roles = []
    for a in areas:
        roles += ROLE_MAP_BASE.get(a, [])
    roles = list(dict.fromkeys(roles))
    base = roles[:2] if roles else areas[:2]
    top = (skills or [])[:3]
    combined = list(dict.fromkeys([*base, *top]))
    return ", ".join(combined) if combined else "empleo"


def generar_boolean_search(areas, seniority, skills):
    roles = []
    for a in areas:
        roles += ROLE_MAP_BASE.get(a, [])
    roles = list(dict.fromkeys(roles))
    role_group = "(" + " OR ".join(f'"{r}"' for r in roles[:4]) + ")" if roles else ""
    skill_group = "(" + " OR ".join(f'"{s}"' for s in (skills or [])[:4]) + ")" if skills else ""
    nivel_map = {
        "junior": '("junior" OR "trainee" OR "sin experiencia")',
        "semi_senior": '"semi senior"',
        "senior": '"senior"',
        "gerencial": '("gerente" OR "director")',
    }
    nivel_group = nivel_map.get(seniority, "")
    parts = [p for p in (role_group, skill_group, nivel_group) if p]
    return " AND ".join(parts) if parts else "empleo"


def generar_kit_links(areas, seniority, skills, country):
    cc = detectar_codigo_pais(country) or "ar"
    simple = generar_palabras_simples(areas, skills)
    boolean = generar_boolean_search(areas, seniority, skills)
    primer_termino = simple.split(",")[0].strip()
    q_simple = quote(simple)
    q_boolean = quote(boolean)
    q_loc = quote(country) if country else ""
    slug = slugify(primer_termino) or "empleo"

    indeed_host = INDEED_DOMAINS.get(cc, "www.indeed.com")
    ct_host = COMPUTRABAJO_DOMAINS.get(cc, "www.computrabajo.com")
    bm_host = BUMERAN_DOMAINS.get(cc, "www.bumeran.com.ar")

    links = [
        ("LinkedIn", f"https://www.linkedin.com/jobs/search/?keywords={q_boolean}" + (f"&location={q_loc}" if country else "")),
        ("Indeed", f"https://{indeed_host}/jobs?q={q_boolean}" + (f"&l={q_loc}" if country else "")),
        ("Computrabajo", f"https://{ct_host}/trabajo-de-{slug}"),
        ("Bumeran", f"https://{bm_host}/empleos-busqueda-{slug}.html"),
        ("Glassdoor", f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q_simple}"),
        ("InfoJobs (España)", f"https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={q_simple}"),
    ]
    return simple, boolean, links


def send_kit_email(user):
    """Manda, UNA sola vez por usuario, el Kit de Búsqueda Laboral: las
    cadenas de búsqueda + los links a portales grandes + la planilla de
    seguimiento. Devuelve False si no se pudo mandar (para no marcarlo
    como enviado y reintentar en la próxima corrida)."""
    areas = user.get("areas") or []
    if not areas:
        print(f"Sin rubro para armar el kit de {user['email']}, se omite (se reintenta cuando cargue un rubro)")
        return False

    seniority = user.get("seniority") or "cualquiera"
    skills = list(dict.fromkeys((user.get("skills") or []) + (user.get("keywords") or [])))
    country = user.get("country")

    simple, boolean, links = generar_kit_links(areas, seniority, skills, country)

    links_html = "".join(f"""
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #eee;font-size:14px">
          <b>{name}</b> — <a href="{url}" style="color:#2563eb;text-decoration:none">Abrir búsqueda y crear alerta →</a>
        </td>
      </tr>""" for name, url in links)

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <h2 style="background:linear-gradient(90deg,#6d28d9,#db2777);-webkit-background-clip:text;background-clip:text;color:transparent">🎁 Tu Kit de Búsqueda Laboral</h2>
      <p style="color:#444;font-size:14px">Armamos esto con tu perfil para que también puedas activar alertas en los
      portales que nosotros no podemos revisar automáticamente (LinkedIn, Indeed, Computrabajo y más).
      <b>Guardá este mail</b> — esto no queda guardado en ningún otro lado.</p>

      <p style="font-size:13px;color:#52525b;font-weight:bold;margin-bottom:4px">Búsqueda simple — pegala en Computrabajo, Bumeran o cualquier buscador básico:</p>
      <div style="background:#f8f8fb;border:1px solid #e4e4e7;border-radius:8px;padding:10px 12px;font-size:13px;margin-bottom:14px">{simple}</div>

      <p style="font-size:13px;color:#52525b;font-weight:bold;margin-bottom:4px">Búsqueda avanzada — pegala en LinkedIn, Indeed o buscadores con operadores:</p>
      <div style="background:#f8f8fb;border:1px solid #e4e4e7;border-radius:8px;padding:10px 12px;font-size:13px;margin-bottom:14px">{boolean}</div>

      <p style="font-size:13px;color:#52525b;font-weight:bold;margin-bottom:6px">O abrí la búsqueda ya armada con un clic:</p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px">{links_html}</table>

      <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:10px;padding:14px 16px;margin-bottom:8px">
        <b>📈 No hace falta instalar nada ni tener cuenta de Google:</b> registrá cada resultado acá y te mandamos coaching automático por mail.<br>
        <a href="https://kxl100rx.github.io/trabajaya/seguimiento.html" style="color:#6d28d9;font-weight:bold;text-decoration:none">Registrar seguimiento →</a>
      </div>

      <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:14px 16px;margin-bottom:8px">
        <b>📊 O si preferís una planilla propia:</b> organizá cada postulación, tus alertas y tu plan de capacitación.<br>
        <a href="{TRACKER_URL}" style="color:#16a34a;font-weight:bold;text-decoration:none">Descargar planilla →</a><br>
        <span style="font-size:12px;color:#666">¿No tenés Excel ni Google? Se abre gratis con
        <a href="https://www.libreoffice.org/download/download/" style="color:#16a34a">LibreOffice Calc</a>
        (sin cuenta) o con Google Sheets gratis. Si no querés instalar nada, usá el botón de arriba.</span>
      </div>

      <p style="color:#999;font-size:12px;margin-top:20px">
        Los links son de mejor esfuerzo — si el país no matchea exacto, ajustalo dentro del portal.
        Nunca accedemos a tus cuentas: vos activás cada alerta con tu propio login.
      </p>
      {_footer_html(user["email"])}
    </div>"""

    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": user["email"]}],
        "subject": "🎁 Tu Kit de Búsqueda Laboral está listo",
        "htmlContent": html,
        "headers": _brevo_headers_for(user["email"]),
    }
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    print(f"Kit email a {user['email']}: status {r.status_code}")
    if r.status_code >= 300:
        print(r.text)
        return False
    return True


def get_users_pending_kit():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users",
        headers=HEADERS,
        params={
            "select": "id,email,areas,seniority,skills,keywords,country",
            "kit_email_sent": "eq.false",
            "active": "eq.true",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mark_kit_sent(user_id):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/users",
        headers=HEADERS,
        params={"id": f"eq.{user_id}"},
        json={"kit_email_sent": True},
        timeout=30,
    )


# ---------------------------------------------------------------------
# Coaching dinámico: lee lo que cada usuario cargó en seguimiento.html
# (tabla "applications"), calcula un diagnóstico y, si hay novedades desde
# el último envío, manda un mail con recomendaciones — misma lógica que la
# hoja "Diagnóstico" de la planilla, pero portada a Python para poder
# correr sola cada 2 horas sin que el usuario tenga que abrir el Excel.
# ---------------------------------------------------------------------
MOTIVO_TIP = {
    "Sin respuesta del reclutador": "El ghosting es muy común — no lo tomes como algo personal, seguí aplicando en volumen y activá más alertas del Kit.",
    "Búsqueda cerrada / pausada por la empresa": "No depende de tu perfil — es una señal de que conviene diversificar más portales y rubros.",
    "Requisito de experiencia no cumplido": "Probá aplicar también a búsquedas de nivel junior/semi senior mientras sumás experiencia, y destacá proyectos personales o voluntariado en el CV.",
    "Habilidad técnica faltante": "Revisá tu Plan de Capacitación: sumar esa habilidad puntual puede destrabar varias postulaciones parecidas.",
    "Expectativa salarial no acorde": "Investigá el rango de mercado de tu rol antes de la entrevista para negociar con datos concretos.",
    "Otro candidato seleccionado": "Buena señal: tu perfil está pasando los filtros. Es cuestión de volumen y timing, seguí aplicando.",
    "Entrevista no fue bien": "Anotá después de cada entrevista qué pregunta te trabó — practicar esas respuestas puntuales mejora mucho la conversión.",
    "No pasó el filtro CV / ATS": "Usá una de las plantillas ATS del formulario y revisá que tu CV tenga las palabras clave exactas de cada aviso.",
    "Proceso muy largo / desistí yo": "Priorizá procesos con tiempos de respuesta más cortos si necesitás una salida rápida.",
    "Otro": "Anotá el detalle en Notas para poder revisar el patrón más adelante.",
}


def get_users_for_coaching():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users",
        headers=HEADERS,
        params={
            "select": "id,email,last_coaching_sent_at",
            "active": "eq.true",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_applications(email):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/applications",
        headers=HEADERS,
        params={"select": "*", "email": f"eq.{email}", "order": "created_at.asc"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def mark_coaching_sent(user_id, when_iso):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/users",
        headers=HEADERS,
        params={"id": f"eq.{user_id}"},
        json={"last_coaching_sent_at": when_iso},
        timeout=30,
    )


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def compute_diagnostico(apps):
    total = len(apps)
    if not total:
        return None

    def count_estado(estado):
        return sum(1 for a in apps if (a.get("estado") or "") == estado)

    sin_resp = count_estado("Sin respuesta")
    entrevista = count_estado("Entrevista")
    oferta = count_estado("Oferta recibida")
    rechazado = count_estado("Rechazado")

    pct_sin_resp = sin_resp / total if total else 0
    tasa_entrevista = (entrevista + oferta) / total if total else 0

    tiempos = []
    for a in apps:
        fp, fr = a.get("fecha_postulacion"), a.get("fecha_respuesta")
        if fp and fr:
            try:
                d1 = datetime.fromisoformat(fp)
                d2 = datetime.fromisoformat(fr)
                tiempos.append((d2 - d1).days)
            except Exception:
                pass
    tiempo_prom = round(sum(tiempos) / len(tiempos), 1) if tiempos else None

    motivo_counts = {}
    for a in apps:
        m = a.get("motivo")
        if m:
            motivo_counts[m] = motivo_counts.get(m, 0) + 1
    top_motivo = max(motivo_counts, key=motivo_counts.get) if motivo_counts else None

    insights = []
    if total < 8:
        insights.append(
            "📈 Volumen bajo: llevás menos de 8 postulaciones registradas. Para tener resultados "
            "significativos, apuntá a aplicar varias por semana usando el Kit de Búsqueda Laboral."
        )
    if pct_sin_resp > 0.5:
        insights.append(
            "⚠️ Más de la mitad de tus postulaciones no tienen respuesta. Suele indicar que el CV no "
            "pasa el filtro ATS o que la búsqueda no está bien afinada — usá una plantilla ATS y revisá "
            "que tu CV repita las palabras clave exactas de cada aviso."
        )
    if total >= 5 and tasa_entrevista < 0.15:
        insights.append(
            "🎯 Tu tasa de avance a entrevista es baja para el volumen que llevás. Antes de seguir "
            "aplicando más, revisá si el CV está bien alineado a los avisos a los que postulás."
        )
    if top_motivo:
        insights.append(f"🔁 Motivo más frecuente: {top_motivo}. {MOTIVO_TIP.get(top_motivo, '')}")
    if oferta > 0:
        insights.append(
            "🎉 ¡Ya tenés ofertas recibidas! Compará condiciones (salario, modalidad, crecimiento) "
            "antes de decidir."
        )

    return {
        "total": total, "sin_resp": sin_resp, "entrevista": entrevista, "oferta": oferta,
        "rechazado": rechazado, "pct_sin_resp": pct_sin_resp, "tasa_entrevista": tasa_entrevista,
        "tiempo_prom": tiempo_prom, "top_motivo": top_motivo, "insights": insights,
    }


def send_coaching_email(email, diag):
    insights_html = "".join(f"<li style='margin-bottom:8px'>{i}</li>" for i in diag["insights"])
    tiempo_txt = f"{diag['tiempo_prom']} días" if diag["tiempo_prom"] is not None else "sin datos aún"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <h2 style="background:linear-gradient(90deg,#6d28d9,#db2777);-webkit-background-clip:text;background-clip:text;color:transparent">📊 Tu diagnóstico de búsqueda</h2>
      <p style="color:#444;font-size:14px">Esto se arma solo con lo que fuiste cargando en
      <a href="https://kxl100rx.github.io/trabajaya/seguimiento.html" style="color:#2563eb">Registrar seguimiento</a>.</p>

      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;font-size:13px">
        <tr><td style="padding:6px 0;color:#666">Postulaciones registradas</td><td style="padding:6px 0;font-weight:bold;text-align:right">{diag['total']}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Sin respuesta</td><td style="padding:6px 0;font-weight:bold;text-align:right">{diag['sin_resp']} ({diag['pct_sin_resp']*100:.0f}%)</td></tr>
        <tr><td style="padding:6px 0;color:#666">Entrevistas</td><td style="padding:6px 0;font-weight:bold;text-align:right">{diag['entrevista']}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Ofertas recibidas</td><td style="padding:6px 0;font-weight:bold;text-align:right">{diag['oferta']}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Tiempo promedio de respuesta</td><td style="padding:6px 0;font-weight:bold;text-align:right">{tiempo_txt}</td></tr>
      </table>

      <p style="font-size:13px;font-weight:bold;color:#52525b">Recomendaciones para vos ahora:</p>
      <ul style="font-size:13.5px;color:#333;padding-left:20px">{insights_html if insights_html else "<li>Seguí cargando postulaciones para que podamos darte recomendaciones más precisas.</li>"}</ul>

      <p style="color:#999;font-size:12px;margin-top:20px">
        Seguí registrando resultados en <a href="https://kxl100rx.github.io/trabajaya/seguimiento.html" style="color:#999">seguimiento.html</a> —
        cuantos más datos cargues, más preciso es este diagnóstico.
      </p>
      {_footer_html(email)}
    </div>"""

    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": email}],
        "subject": "📊 Tu diagnóstico de búsqueda actualizado",
        "htmlContent": html,
        "headers": _brevo_headers_for(email),
    }
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    print(f"Coaching email a {email}: status {r.status_code}")
    if r.status_code >= 300:
        print(r.text)
        return False
    return True


def clean(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss():
    jobs = []
    for feed_cfg in RSS_FEEDS:
        try:
            r = requests.get(feed_cfg["url"], headers=REQUEST_HEADERS, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            for e in feed.entries[:40]:
                jobs.append({
                    "title": e.get("title", ""),
                    "desc": clean(e.get("summary", "") or e.get("description", "")),
                    "link": e.get("link", ""),
                    "lang": feed_cfg["lang"],
                    "location": "",  # estos feeds son 100% remoto, sin localidad
                })
        except Exception as ex:
            print(f"Error leyendo {feed_cfg['url']}: {ex}")
    return jobs


def fetch_json():
    jobs = []
    for feed_cfg in JSON_FEEDS:
        try:
            r = requests.get(feed_cfg["url"], headers=REQUEST_HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            if feed_cfg["kind"] == "himalayas":
                for j in (data.get("jobs") or [])[:60]:
                    jobs.append({
                        "title": j.get("title", ""),
                        "desc": clean(j.get("description", "") or j.get("excerpt", "")),
                        "link": j.get("applicationLink") or f"https://himalayas.app/jobs/{j.get('guid','')}",
                        "lang": feed_cfg["lang"],
                        "location": "",
                    })
            elif feed_cfg["kind"] == "jobicy":
                for j in (data.get("jobs") or [])[:60]:
                    jobs.append({
                        "title": j.get("jobTitle", j.get("title", "")),
                        "desc": clean(j.get("jobDescription", "") or j.get("jobExcerpt", "")),
                        "link": j.get("url", ""),
                        "lang": feed_cfg["lang"],
                        "location": "",
                    })
            elif feed_cfg["kind"] == "remotive":
                for j in (data.get("jobs") or [])[:60]:
                    jobs.append({
                        "title": j.get("title", ""),
                        "desc": clean(j.get("description", "")),
                        "link": j.get("url", ""),
                        "lang": feed_cfg["lang"],
                        "location": "",
                    })
            elif feed_cfg["kind"] == "remoteok":
                # el primer elemento del array es un aviso legal, no una oferta
                for j in [x for x in data if isinstance(x, dict) and x.get("position")][:60]:
                    jobs.append({
                        "title": j.get("position", ""),
                        "desc": clean(j.get("description", "")),
                        "link": j.get("url") or j.get("apply_url", ""),
                        "lang": feed_cfg["lang"],
                        "location": "",
                    })
            elif feed_cfg["kind"] == "workingnomads":
                for j in (data if isinstance(data, list) else [])[:60]:
                    jobs.append({
                        "title": j.get("title", ""),
                        "desc": clean(j.get("description", "")),
                        "link": j.get("url", ""),
                        "lang": feed_cfg["lang"],
                        "location": "",
                    })
            elif feed_cfg["kind"] == "arbeitnow":
                for j in (data.get("data") or [])[:60]:
                    jobs.append({
                        "title": j.get("title", ""),
                        "desc": clean(j.get("description", "")),
                        "link": j.get("url", ""),
                        "lang": feed_cfg["lang"],
                        "location": j.get("location") or "",
                    })
            elif feed_cfg["kind"] == "vacantesdigitales":
                for j in (data.get("data") or [])[:80]:
                    locality = j.get("address_locality") or ""
                    country_code = j.get("address_country") or ""
                    location = ", ".join(p for p in [locality, country_code] if p)
                    jobs.append({
                        "title": j.get("title", ""),
                        "desc": clean(j.get("summary", "") or j.get("content", "")),
                        "link": j.get("apply_url") or j.get("url", ""),
                        "lang": feed_cfg["lang"],
                        "location": location,
                    })
        except Exception as ex:
            print(f"Error leyendo {feed_cfg['url']}: {ex}")
        time.sleep(1)  # pequeña pausa entre plataformas distintas, por prolijidad
    return jobs


def _title_key(title):
    """Clave conservadora para detectar el mismo aviso publicado en mas de un
    portal (cross-posting): titulo normalizado, sin acentos ni puntuacion.
    No usa similitud difusa a proposito: preferimos mandar un duplicado a
    ocultar una oferta real distinta."""
    t = normalize_text(title)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t


def fetch_jobs():
    jobs = fetch_rss() + fetch_json()
    # de-duplicar por link y por titulo identico entre fuentes distintas
    seen_links, seen_titles, unique = set(), set(), []
    dup_cross = 0
    for j in jobs:
        if not j["link"] or j["link"] in seen_links:
            continue
        tk = _title_key(j["title"])
        if tk and len(tk) >= 12 and tk in seen_titles:
            dup_cross += 1
            continue
        seen_links.add(j["link"])
        if tk:
            seen_titles.add(tk)
        unique.append(j)
    if dup_cross:
        print(f"{dup_cross} aviso(s) duplicados entre portales colapsados")
    return unique


def get_active_users():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/users",
        headers=HEADERS,
        params={
            "select": "id,email,keywords,skills,areas,languages,work_mode,country,city,travel_radius,seniority",
            "active": "eq.true",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_sent_links(user_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/sent_jobs",
        headers=HEADERS,
        params={"select": "job_link", "user_id": f"eq.{user_id}"},
        timeout=30,
    )
    r.raise_for_status()
    return {row["job_link"] for row in r.json()}


def mark_sent_many(user_id, links):
    """Registra en UNA sola request todas las ofertas enviadas a un usuario."""
    if not links:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/sent_jobs",
        headers={**HEADERS, "Prefer": "resolution=ignore-duplicates"},
        json=[{"user_id": user_id, "job_link": link} for link in links],
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"No se pudo registrar sent_jobs para {user_id}: {r.status_code} {r.text[:200]}")


def matches_seniority(text, seniority):
    """Si el usuario eligio un nivel especifico, el aviso tiene que
    mencionarlo. Si eligio "cualquiera" (o no eligio nada), no filtra por
    nivel: sirve para cualquier persona y seniority."""
    if not seniority or seniority == "cualquiera":
        return True
    terms = SENIORITY_TERMS.get(seniority)
    if not terms:
        return True
    t = text.lower()
    return any(term in t for term in terms)


def match_score(job_text, user_terms):
    t = job_text.lower()
    return sum(1 for term in user_terms if term and term.lower() in t)


def normalize_text(s):
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def es_presencial_o_hibrido(text):
    t = normalize_text(text)
    return any(w in t for w in ["presencial", "hibrido", "onsite", "on-site", "in office", "in-office"])


def fuera_de_zona(job, user):
    """Solo filtra cuando el usuario eligio radio 'zona' (su barrio/localidad
    nomas) y cargo su ciudad: si el aviso es presencial/hibrido y menciona
    una localidad que NO es la suya, lo dejamos afuera. Sin ciudad cargada,
    o con otro radio, no filtramos nada -- preferimos mostrar de mas a
    mostrar de menos mientras no tengamos distancia real (lat/long)."""
    travel_radius = user.get("travel_radius") or "cualquiera"
    city = (user.get("city") or "").strip()
    if travel_radius != "zona" or not city:
        return False
    full_text = job["title"] + " " + job["desc"]
    if not es_presencial_o_hibrido(full_text) and not job.get("location"):
        return False  # remoto puro: nunca lo filtramos por ciudad
    location = job.get("location") or ""
    if not location:
        return False  # sin dato de localidad, no arriesgamos a ocultarlo
    return normalize_text(city) not in normalize_text(location)


SCAM_SIGNALS = [
    ("pago para postularte", ["pagar la inscripcion", "abona un arancel", "deposito para reservar",
                               "envianos $", "envianos usd", "cuota de ingreso", "comprar el kit",
                               "inversion inicial", "vacante paga un bono de ingreso"]),
    ("esquema piramidal / multinivel", ["multinivel", "reclutamiento de red", "gana por cada persona que sumes",
                                         "sistema de referidos ilimitado", "libertad financiera",
                                         "se tu propio jefe sin experiencia"]),
    ("promesas poco creibles", ["gana dinero facil", "gana dinero rapido", "trabaja 2 horas y gana",
                                 "sin experiencia gana miles", "ingresos ilimitados desde tu casa"]),
    ("pide datos sensibles antes de una entrevista", ["envia tu dni por whatsapp", "numero de cuenta bancaria",
                                                        "envia una foto de tu documento", "clave bancaria",
                                                        "send your bank details", "send a copy of your id"]),
    ("pide comprar equipo o insumos antes de empezar", ["comprar tu equipo", "compra de insumos", "adquirir el kit",
                                                         "comprar la notebook", "purchase equipment", "buy your own equipment"]),
    ("pago fuera de nomina o en criptomonedas", ["pago en cripto", "pago en criptomonedas", "pago en bitcoin", "pago en usdt",
                                                  "paid in crypto", "payment in bitcoin", "fuera de nomina", "sin recibo de sueldo"]),
    ("contratacion sin entrevista ni proceso", ["contratacion inmediata sin entrevista", "sin entrevista", "no necesitas cv",
                                                "no interview needed", "no interview required", "hired immediately"]),
    ("urgencia sospechosa sin datos de la empresa", ["cupos limitados", "responde en 2 horas", "responde en las proximas horas",
                                                     "urgent hiring", "empresa confidencial contrata ya", "ultimos cupos"]),
    ("solicita gift cards como pago o deposito", ["gift card", "gift cards", "tarjeta de regalo", "tarjetas de regalo",
                                                  "steam card", "google play card"]),
    ("estafa de tareas con retiro bloqueado", ["completa tareas simples y gana", "tareas simples desde tu celular",
                                                "desbloquea tu retiro", "para retirar tus ganancias deposita",
                                                "task-based earnings", "complete simple tasks and earn"]),
    ("pide instalar apps fuera de tiendas oficiales", ["instala el apk", "descarga el apk", "te enviamos el apk",
                                                        "instalador por whatsapp", "install the apk", "download the apk"]),
    ("pide usar tu cuenta bancaria para recibir y reenviar pagos", ["recibir pagos en tu cuenta", "reenviar el dinero",
                                                                     "transferir a otra cuenta", "usar tu cuenta bancaria para",
                                                                     "receive payments on your account", "forward the funds",
                                                                     "money transfer agent"]),
    ("cobra curso o capacitacion obligatoria antes de contratar", ["curso obligatorio pago", "capacitacion paga obligatoria",
                                                                    "seguro de contratacion", "garantia de puesto",
                                                                    "abonar la capacitacion", "paid training fee",
                                                                    "training fee required"]),
    ("aviso en ingles con patrones de scam para puesto local", ["wire transfer required", "processing fee", "send money via",
                                                                "western union", "moneygram", "cashier's check", "cheque falso"]),
]


def senales_de_alerta(job):
    """Heuristica simple y conservadora (nunca oculta la oferta, solo
    advierte) para detectar patrones tipicos de estafas o "trabajo desde
    casa" fraudulento, muy comunes en portales de LatAm (Computrabajo tiene
    denuncias publicas de este tipo). Preferimos falsos negativos a falsos
    positivos: solo marca frases bastante explicitas, no rechaza por
    palabras sueltas como "remoto" o "flexible"."""
    t = normalize_text(job.get("title", "") + " " + job.get("desc", ""))
    razones = []
    for etiqueta, frases in SCAM_SIGNALS:
        if any(normalize_text(f) in t for f in frases):
            razones.append(etiqueta)
    return razones


def perfil_resumen(user):
    langs = user.get("languages") or []
    mode = user.get("work_mode") or "remoto_mundial"
    mode_txt = WORK_MODE_LABEL.get(mode, mode)
    seniority = user.get("seniority") or "cualquiera"
    seniority_txt = SENIORITY_LABEL.get(seniority, seniority)
    if langs:
        regiones = "; ".join(LANG_REGIONS.get(l, l) for l in langs)
    else:
        regiones = LANG_REGIONS["en"]
    pais = user.get("country")
    pais_txt = f" ({pais})" if pais else ""
    return (
        f"Buscamos ofertas <b>{mode_txt}</b>{pais_txt} para nivel <b>{seniority_txt}</b>. "
        f"Por tus idiomas, tu alcance potencial es: {regiones}. "
        f"Por ahora las fuentes automaticas son principalmente en ingles; a medida que sumemos mas portales "
        f"locales vas a recibir tambien ofertas en tus otros idiomas."
    )


def _esc(t):
    return html_lib.escape(str(t or ""), quote=True)


def _footer_html(to_email):
    baja = f"mailto:{SUPPORT_EMAIL}?subject=BAJA&body=" + quote(f"Quiero darme de baja de las alertas: {to_email}")
    return f"""
      <p style="color:#999;font-size:12px;margin-top:24px;line-height:1.6">
        Recibis esto porque te registraste en <a href="{SITE_URL}" style="color:#999">trabajaya</a>, el buscador automatico de empleo.<br>
        <a href="{baja}" style="color:#999">Darme de baja</a> ·
        <a href="{SITE_URL}transparencia.html" style="color:#999">Como funciona</a> ·
        <a href="{SITE_URL}privacidad.html" style="color:#999">Privacidad</a>
      </p>"""


def _brevo_headers_for(to_email):
    """Headers List-Unsubscribe (RFC 8058): Gmail/Yahoo los exigen a remitentes
    masivos y mejoran mucho la entregabilidad."""
    baja = f"mailto:{SUPPORT_EMAIL}?subject=BAJA%20{quote(to_email)}"
    return {
        "List-Unsubscribe": f"<{baja}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def send_email(to_email, jobs, user):
    """Devuelve True solo si Brevo acepto el mail. Si devuelve False, las
    ofertas NO se marcan como enviadas y se reintentan en la proxima corrida
    (antes se marcaban igual y el usuario las perdia para siempre)."""
    rows = ""
    for j in jobs:
        razones = senales_de_alerta(j)
        warning_html = ""
        if razones:
            warning_html = (
                f'<p style="margin:6px 0 0;background:#fef2f2;border:1px solid #fecaca;color:#991b1b;'
                f'font-size:12px;border-radius:6px;padding:6px 8px">'
                f'⚠️ Señales de alerta: {_esc(", ".join(razones))}. Revisá bien antes de compartir datos o pagar '
                f"cualquier monto — un empleo real nunca te cobra a vos.</p>"
            )
        title = _esc(j["title"])
        link = _esc(j["link"])
        desc = _esc(j["desc"][:220])
        wa_text = quote(f"Mirá esta oferta de trabajo: {j['title']} {j['link']} (encontrada con trabajaya {SITE_URL})")
        report = f"mailto:{SUPPORT_EMAIL}?subject=" + quote("Oferta rota o vencida") + "&body=" + quote(f"Link: {j['link']}")
        rows += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #eee">
            <a href="{link}" style="font-weight:bold;color:#2563eb;text-decoration:none">{title}</a>
            <p style="margin:4px 0 0;color:#555;font-size:14px">{desc}...</p>
            {warning_html}
            <p style="margin:6px 0 0;font-size:12px">
              <a href="https://wa.me/?text={wa_text}" style="color:#16a34a;text-decoration:none;font-weight:bold">📤 Compartir por WhatsApp</a>
              &nbsp;·&nbsp;
              <a href="{report}" style="color:#a1a1aa;text-decoration:none">Reportar oferta rota/vencida</a>
            </p>
          </td>
        </tr>"""
    resumen = perfil_resumen(user)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <h2 style="background:linear-gradient(90deg,#6d28d9,#db2777);-webkit-background-clip:text;background-clip:text;color:transparent">Nuevas ofertas para vos</h2>
      <div style="background:#f4f0ff;border:1px solid #e4d9ff;border-radius:10px;padding:12px 16px;font-size:13px;color:#4c1d95;margin-bottom:16px">
        {resumen}
      </div>
      <p>Encontramos {len(jobs)} oferta(s) que podrian matchear con tu perfil.</p>
      <table style="width:100%;border-collapse:collapse">{rows}</table>
      {_footer_html(to_email)}
    </div>"""

    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": f"🔎 {len(jobs)} nuevas ofertas de trabajo para vos",
        "htmlContent": html,
        "headers": _brevo_headers_for(to_email),
    }
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as ex:
        print(f"Email a {to_email}: error de red {ex}")
        return False
    print(f"Email a {to_email}: status {r.status_code}")
    if r.status_code >= 300:
        print(r.text)
        return False
    return True


def main():
    pending_kit = get_users_pending_kit()
    print(f"{len(pending_kit)} usuario(s) nuevo(s) esperando el Kit de Búsqueda Laboral")
    for user in pending_kit:
        if send_kit_email(user):
            mark_kit_sent(user["id"])

    coaching_users = get_users_for_coaching()
    coaching_sent_count = 0
    for cu in coaching_users:
        email = cu.get("email")
        if not email:
            continue
        apps = get_applications(email)
        if not apps:
            continue
        last_sent = _parse_iso(cu.get("last_coaching_sent_at"))
        newest_app = None
        for a in apps:
            ca = _parse_iso(a.get("created_at"))
            if ca and (newest_app is None or ca > newest_app):
                newest_app = ca
        now = datetime.now(timezone.utc)
        should_send = False
        if last_sent is None:
            should_send = True
        else:
            hours_since = (now - last_sent).total_seconds() / 3600
            if hours_since >= 20 and newest_app and newest_app > last_sent:
                should_send = True
        if not should_send:
            continue
        diag = compute_diagnostico(apps)
        if send_coaching_email(email, diag):
            mark_coaching_sent(cu["id"], now.isoformat())
            coaching_sent_count += 1
    print(f"{coaching_sent_count} mail(s) de coaching enviados")

    users = get_active_users()
    all_jobs = fetch_jobs()
    print(f"{len(users)} usuarios activos, {len(all_jobs)} avisos leidos de los feeds")

    for user in users:
        user_terms = (
            (user.get("keywords") or [])
            + (user.get("skills") or [])
            + (user.get("areas") or [])
        )
        seniority = user.get("seniority") or "cualquiera"
        sent_links = get_sent_links(user["id"])

        scored = []
        for job in all_jobs:
            if job["link"] in sent_links:
                continue
            full_text = job["title"] + " " + job["desc"]
            if not matches_seniority(full_text, seniority):
                continue
            score = match_score(full_text, user_terms) if user_terms else 0
            if user_terms and score == 0:
                continue
            if fuera_de_zona(job, user):
                continue
            # las coincidencias en el titulo valen doble: son mucho mas relevantes
            score += match_score(job["title"], user_terms) if user_terms else 0
            scored.append((score, job))

        # las mejores primero (antes se mandaban las primeras 15 en orden de feed)
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = [j for _, j in scored[:MAX_JOBS_PER_MAIL]]
        if matches:
            if send_email(user["email"], matches, user):
                mark_sent_many(user["id"], [j["link"] for j in matches])
            else:
                print(f"Mail a {user['email']} fallo: se reintenta en la proxima corrida")
        else:
            print(f"Sin novedades para {user['email']}")

    print("Listo:", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
