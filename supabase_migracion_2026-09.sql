-- =====================================================================
-- MIGRACIÓN 2026-09 — correr UNA vez en Supabase > SQL Editor > Run.
-- Es idempotente (se puede correr dos veces sin romper nada).
-- Todo el código nuevo (index.html, scripts/match_and_notify.py) es
-- auto-adaptativo: funciona ANTES de correr esto (modo viejo) y DESPUÉS
-- (modo nuevo con doble opt-in, preferencias, digest y referidos).
-- =====================================================================

-- 1) Columnas nuevas en users --------------------------------------------
alter table users add column if not exists city text;
alter table users add column if not exists travel_radius text default 'cualquiera';
-- doble opt-in
alter table users add column if not exists confirmed boolean not null default false;
alter table users add column if not exists confirm_token uuid not null default gen_random_uuid();
alter table users add column if not exists confirm_sent_at timestamptz;
-- frecuencia de alertas: 'inmediato' (cada corrida), 'diario', 'semanal'
alter table users add column if not exists frequency text not null default 'inmediato';
alter table users add column if not exists last_digest_sent_at timestamptz;
-- referidos
alter table users add column if not exists referred_by text;

-- Los que ya estaban anotados quedan confirmados (ya venían recibiendo mails).
update users set confirmed = true where confirmed = false and created_at < now() - interval '5 minutes';

create unique index if not exists users_confirm_token_idx on users(confirm_token);

-- 2) Alta por RPC (reemplaza el upsert directo desde el navegador) --------
-- Antes: el navegador hacía upsert sobre users con la anon key. Eso obliga a
-- una política de UPDATE abierta (cualquiera podría pisar el perfil de otro
-- con solo saber su mail). Ahora el alta pasa por esta función:
--  - si el mail no existe: lo crea (sin confirmar).
--  - si existe: actualiza preferencias pero NO cambia confirmed ni token.
create or replace function signup(
  p_email text, p_keywords text[], p_skills text[], p_areas text[], p_cv_text text,
  p_languages text[], p_work_mode text, p_country text, p_city text,
  p_travel_radius text, p_seniority text, p_referred_by text default null
) returns void
language plpgsql security definer set search_path = public as $$
begin
  if p_email is null or p_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'email inválido';
  end if;
  insert into users (email, keywords, skills, areas, cv_text, languages, work_mode,
                     country, city, travel_radius, seniority, referred_by, active)
  values (lower(trim(p_email)), coalesce(p_keywords,'{}'), coalesce(p_skills,'{}'),
          coalesce(p_areas,'{}'), p_cv_text, coalesce(p_languages,'{}'),
          coalesce(p_work_mode,'remoto_mundial'), p_country, p_city,
          coalesce(p_travel_radius,'cualquiera'), coalesce(p_seniority,'cualquiera'),
          nullif(left(p_referred_by, 64), ''), true)
  on conflict (email) do update set
    keywords = excluded.keywords, skills = excluded.skills, areas = excluded.areas,
    cv_text = excluded.cv_text, languages = excluded.languages, work_mode = excluded.work_mode,
    country = excluded.country, city = excluded.city, travel_radius = excluded.travel_radius,
    seniority = excluded.seniority, active = true;
end $$;
grant execute on function signup(text,text[],text[],text[],text,text[],text,text,text,text,text,text) to anon;

-- Cerramos el INSERT directo desde anon: ahora todo entra por signup().
drop policy if exists "cualquiera puede registrarse" on users;

-- 3) Confirmación de mail (doble opt-in) ---------------------------------
create or replace function confirm_email(p_token uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update users set confirmed = true, active = true where confirm_token = p_token;
  get diagnostics n = row_count;
  return n > 0;
end $$;
grant execute on function confirm_email(uuid) to anon;

-- 4) Centro de preferencias (el token del mail es la "llave") --------------
create or replace function get_prefs(p_token uuid)
returns table(email text, active boolean, frequency text, confirmed boolean, referidos int)
language sql security definer set search_path = public as $$
  select u.email, u.active, u.frequency, u.confirmed,
         (select count(*)::int from users r where r.referred_by = u.email and r.confirmed)
  from users u where u.confirm_token = p_token;
$$;
grant execute on function get_prefs(uuid) to anon;

create or replace function set_prefs(p_token uuid, p_active boolean, p_frequency text)
returns boolean language plpgsql security definer set search_path = public as $$
declare n int;
begin
  if p_frequency not in ('inmediato','diario','semanal') then
    raise exception 'frecuencia inválida';
  end if;
  update users set active = p_active, frequency = p_frequency where confirm_token = p_token;
  get diagnostics n = row_count;
  return n > 0;
end $$;
grant execute on function set_prefs(uuid, boolean, text) to anon;

-- Borrado total ("derecho al olvido"): borra usuario, enviados y seguimiento.
create or replace function delete_me(p_token uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare v_email text;
begin
  select email into v_email from users where confirm_token = p_token;
  if v_email is null then return false; end if;
  delete from applications where email = v_email;
  delete from users where email = v_email;  -- sent_jobs cae por cascade
  return true;
end $$;
grant execute on function delete_me(uuid) to anon;

-- 5) Seguimiento: solo usuarios confirmados pueden cargar postulaciones ----
drop policy if exists "cualquiera puede registrar su seguimiento" on applications;
-- (la política no puede leer users directamente porque anon no tiene SELECT
--  ahí; se usa una función security definer que solo devuelve true/false)
create or replace function email_confirmado(p_email text)
returns boolean language sql security definer set search_path = public stable as $$
  select exists (select 1 from users u where u.email = lower(trim(p_email)) and u.confirmed);
$$;
grant execute on function email_confirmado(text) to anon;
create policy "solo usuarios confirmados registran seguimiento"
  on applications for insert to anon
  with check (email_confirmado(email));

-- 6) Estadísticas públicas (se recrea porque cambia la forma de salida)
drop function if exists public_stats();
create function public_stats()
returns table(usuarios_activos int, ofertas_enviadas_semana int, estafas_detectadas int)
language sql security definer set search_path = public as $$
  select (select count(*)::int from users where active and confirmed),
         (select count(*)::int from sent_jobs where sent_at > now() - interval '7 days'),
         0;
$$;
grant execute on function public_stats() to anon;
