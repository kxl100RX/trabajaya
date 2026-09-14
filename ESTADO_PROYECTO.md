# Estado del proyecto — trabajaya

> Este archivo existe para que cualquier sesión de Claude (o vos, Ruben) pueda
> retomar el proyecto sin tener que re-explicar qué se hizo. Se actualiza cada
> vez que hay un cambio de fondo. Última actualización: 14/09/2026.

## Qué es esto
Plataforma gratuita de alertas de empleo. Rastrea ofertas en portales grandes
(LinkedIn, Indeed, Computrabajo, etc.) y también en webs/redes de empresas que
no publican en esos portales. El usuario se anota una vez y recibe por mail
las ofertas que matchean su perfil. Hay una capa Premium opcional (asistente
de IA para acompañar postulaciones).

- Repo: `kxl100RX/trabajaya` (antes `kxl100RX/trabajoya`, renombrado el 18/08/2026)
- Sitio en vivo: **https://kxl100rx.github.io/trabajaya/** (la URL vieja
  `.../trabajoya/` quedó 404 — no redirige, hay que actualizar cualquier link
  guardado o compartido)

## Marca: trabajoya → trabajaya
"trabajoya" ya estaba registrada por otro titular en INPI, así que se decidió
renombrar todo el proyecto a **trabajaya**.

Hecho:
- Rebranding de todo el texto visible del sitio (index.html, premium.html,
  privacidad.html, seguimiento.html, imagen OG) vía subida directa por la web
  de GitHub (el push por git está bloqueado para este repo desde esta sesión
  en la nube — se resuelve usando el navegador Chrome del usuario, que tiene
  sesión propia logueada como owner).
- Repositorio renombrado de `trabajoya` a `trabajaya` en GitHub Settings.
- Corregidas todas las URLs internas que quedaron apuntando a la URL vieja
  después del rename: `canonical`, `og:url`, `og:image`, `sitemap.xml`,
  `robots.txt` (esto se detectó recién en esta pasada de validación — quedaban
  rotas apuntando a `.../trabajoya/` que ya no existe).
- Agregado `LICENSE` (todos los derechos reservados) — el repo tiene que ser
  público para que GitHub Pages funcione gratis, así que "privado" no es
  técnicamente posible sin pagar GitHub Pro. La licencia protege legalmente
  el código aunque sea visible/clonable.

## Trámite de marca (INPI, Argentina)
Solicitud de TRABAJAYA, clase 35, cargada y firmada en el Portal de Trámites
del INPI. Se generó VEP de pago (Nro E-RECAUDA 202600118067, $39.735) para
pagar con QR / Mercado Pago.
**Pendiente de confirmar**: si el pago del VEP se completó. Si no está pagado,
hay que volver a INPI y pagarlo — sin el pago el trámite no avanza.
Una vez pagado: acreditación (hasta 15 días hábiles) y después ventana de
oposición de terceros (~30 días).

## Dominio
- `trabajaya.com` es un dominio premium/reventa: **US$3.380** (confirmado en
  dos registradores distintos, Namecheap y GoDaddy — precio real, no es un
  error). Descartado por precio.
- Decisión final de Ruben: **trabajayajobs.com** (más corto y parecido
  disponible a precio normal, ~US$0.01 primer año / ~US$23/año renovación en
  GoDaddo, o al costo ~US$10-11/año en Cloudflare Registrar).
- **Postergado explícitamente por Ruben** ("dejemos para más adelante lo del
  dominio") — no comprar hasta que lo pida de nuevo.
- El sitio puede seguir en GitHub Pages sin problema aunque se compre un
  dominio propio: solo hay que agregar un archivo `CNAME` en la raíz del repo
  + configurar los registros DNS (A para el apex, CNAME para www). HTTPS
  gratis y automático.

## Mail de contacto
Necesidad: una casilla tipo `info@trabajaya.com` (o similar) para reclamos
(idealmente resueltos por un bot tipo "dejá tu sugerencia") y para
propuestas/inversión/charlas, sin exponer el Gmail personal de Ruben.

Recomendación dada: **SimpleLogin** (de Proton) — 10 alias gratis, permite
responder desde el alias sin pagar, mejor reputación de entrega que Firefox
Relay (que cobra por responder). Alternativa: addy.io (alias ilimitados
gratis). Funciona ya mismo sin dominio propio (usa un dominio compartido del
servicio); cuando se compre el dominio propio, se puede migrar el alias a
`info@trabajaya.com` con el mismo servicio.

**Pendiente**: crear la cuenta real. Se le preguntó a Ruben si prefería que
se la arme directamente o armarla él mismo — no llegó a responder antes de
que cambiara de tema.

## SEO / posicionamiento (explicado, no ejecutado más allá de lo ya hecho)
- Orgánico (gratis, lento — meses): contenido + indexación (sitemap.xml,
  robots.txt, Search Console — ya están en el repo) + backlinks.
- Pago (Google Ads / Meta Ads): pay-per-click, no mejora el ranking orgánico,
  es un canal aparte.
- El posicionamiento no depende de que el sitio esté en GitHub Pages — Google
  indexa igual. Lo que sí importa es tener URLs estables (por eso la corrección
  de canonical/sitemap de este documento era importante).

## Backlog
Backlog completo, categorizado (Fundacional/urgente, Costo cero técnico,
Deseable, Escalabilidad) y con notas de opinión estratégica, entregado en dos
formatos:
- `trabajaya-backlog-escalamiento.xlsx` (Excel)
- Tablero HTML interactivo, filtrable por fase, agrupado por categoría —
  persistido como artifact de Cowork en el escritorio de Ruben
  ("trabajaya-backlog").

## Cambios del 14/09/2026 (lote consolidado, 27 días de backlog)
- `scripts/match_and_notify.py`: URLs viejas `trabajoya` corregidas (4), 14 categorías
  de detección de estafas (eran 4), dedup de avisos cross-portal por título,
  ranking por relevancia (antes: primeras 15 en orden de feed), escape HTML de
  títulos/descripciones, botón "Compartir por WhatsApp" y "Reportar oferta rota"
  por oferta, footer "Darme de baja" + headers `List-Unsubscribe` en los 3 mails,
  timeout en feeds RSS (antes podían colgar la corrida), `sent_jobs` en lote y
  **solo se marca enviado si Brevo aceptó el mail** (antes se perdían ofertas
  si el envío fallaba). Etiqueta `hibrido` agregada (antes salía el código crudo).
- `index.html`: FAQPage JSON-LD, accesibilidad (`aria-live` en #msg,
  `aria-required`, `autocomplete=email`), link a "Cómo funciona".
- `transparencia.html` (nueva), `privacidad.html` (ya no dice "sin analítica":
  el sitio tiene GA4 desde el commit 4f35157), `sitemap.xml`, `supabase_schema.sql`
  (columnas `city`/`travel_radius` que el formulario ya enviaba).
- Variable opcional nueva para Actions: `SUPPORT_EMAIL` (destino de bajas y
  reportes; si no está, usa `SENDER_EMAIL`).

## Cosas que quedaron pendientes / a retomar
1. Confirmar si se pagó el VEP de INPI.
2. Crear la cuenta de SimpleLogin para el mail de contacto.
3. Cuando Ruben lo pida: comprar `trabajayajobs.com` y configurar CNAME + DNS.
4. Revisar periódicamente que no queden URLs viejas (`.../trabajoya/`) en
   contenido nuevo que se agregue — el error de canonical/sitemap roto
   después del rename es un ejemplo de lo que hay que chequear siempre
   después de un cambio de nombre/URL.
5. Seguir la instrucción explícita de Ruben de traer criterio propio al
   proyecto y no solo ejecutar órdenes — priorizar, opinar, avisar riesgos
   antes de que los pida.

## Cómo se está trabajando técnicamente (para que la próxima sesión no se
pierda)
- Esta sesión en la nube **no tiene permiso de `git push`** a este repo (el
  proxy de git lo bloquea). La forma que funciona es usar
  `mcp__claude-in-chrome__*` para operar el navegador Chrome real de Ruben,
  que está logueado en GitHub con permisos de owner, y subir archivos vía la
  web ("Add file" → "Upload files" → completar mensaje de commit → "Commit
  changes"). Ruben pidió explícitamente resolverlo así en vez de pedirle que
  suba archivos él mismo.
- Cambios de configuración de cuenta (rename del repo, visibilidad, etc.)
  requieren confirmación explícita de Ruben en el chat antes de ejecutarse.
