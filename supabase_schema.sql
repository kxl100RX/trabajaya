-- Ejecutar esto UNA vez en Supabase: proyecto > SQL Editor > New query > pegar > Run
-- (Si ya habías creado las tablas antes, este mismo archivo agrega las columnas
-- nuevas de idiomas/modalidad/nivel de experiencia de forma segura con
-- "add column if not exists")

create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  keywords text[] not null default '{}',
  skills text[] not null default '{}',
  areas text[] not null default '{}',
  cv_text text,
  languages text[] not null default '{}',
  work_mode text default 'remoto_mundial',
  country text,
  seniority text default 'cualquiera',
  created_at timestamptz default now(),
  active boolean default true
);

alter table users add column if not exists languages text[] not null default '{}';
alter table users add column if not exists work_mode text default 'remoto_mundial';
alter table users add column if not exists country text;
alter table users add column if not exists seniority text default 'cualquiera';

create table if not exists sent_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  job_link text not null,
  sent_at timestamptz default now(),
  unique(user_id, job_link)
);

-- Seguridad: cualquiera puede registrarse (insert), pero NADIE puede leer
-- la lista de usuarios desde el navegador (protege los mails y CVs).
alter table users enable row level security;
alter table sent_jobs enable row level security;

drop policy if exists "cualquiera puede registrarse" on users;
create policy "cualquiera puede registrarse"
  on users for insert
  to anon
  with check (true);

-- El script automático (GitHub Actions) usa la "service role key",
-- que se salta estas reglas por diseño y sí puede leer todo. Esa key
-- NUNCA va en el sitio web, solo en los Secrets de GitHub.

-- Kit de Búsqueda Laboral por mail (una sola vez por usuario nuevo).
-- El backfill marca a TODOS los ya registrados como "ya enviado" para no
-- mandarles de golpe un mail retroactivo — solo lo reciben los que se
-- anoten de ahora en más.
alter table users add column if not exists kit_email_sent boolean not null default false;
update users set kit_email_sent = true where kit_email_sent = false;

-- ---------------------------------------------------------------------
-- Seguimiento de postulaciones (para coaching dinámico por mail).
-- El candidato carga cada resultado desde seguimiento.html; el robot
-- (GitHub Actions, cada 5hs) lee esto con la service role key y le
-- manda un diagnóstico actualizado por mail cuando hay novedades.
-- ---------------------------------------------------------------------
create table if not exists applications (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  empresa text,
  puesto text,
  portal text,
  fecha_postulacion date,
  estado text,
  fecha_respuesta date,
  motivo text,
  notas text,
  created_at timestamptz default now()
);

alter table applications enable row level security;

drop policy if exists "cualquiera puede registrar su seguimiento" on applications;
create policy "cualquiera puede registrar su seguimiento"
  on applications for insert
  to anon
  with check (true);

-- Sin política de SELECT para "anon": nadie puede leer el seguimiento de
-- otra persona desde el navegador. Solo el script (service role key,
-- nunca expuesta en el sitio) puede leerlo para generar el coaching.

alter table users add column if not exists last_coaching_sent_at timestamptz;

-- Columnas que index.html ya envía desde el formulario (faltaban en este archivo).
alter table users add column if not exists city text;
alter table users add column if not exists travel_radius text default 'cualquiera';
-- Nota: index.html hace UPSERT por email desde el navegador (anon). Para que
-- un usuario ya registrado pueda actualizar su perfil hace falta una política
-- de UPDATE acotada; sin ella el upsert falla con RLS. Revisar en Supabase.
