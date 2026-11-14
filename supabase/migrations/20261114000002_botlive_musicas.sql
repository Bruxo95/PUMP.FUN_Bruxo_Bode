-- 0.32.351 (pedido do dono, 14/11/2026): músicas lofi da SALA LIVE do BOT LIVE (4 playlists por horário). Bucket PRIVADO no
-- Supabase Storage: só o servidor (service key) lê e grava; a SALA LIVE recebe as faixas pela rota /botlive/musica/<id> do site.
-- (O teste local de RLS roda num Postgres sem o esquema storage: aí não faz nada.)
do $$ begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('botlive-music', 'botlive-music', false, 26214400, array['audio/mpeg', 'audio/ogg', 'application/json'])
    on conflict (id) do nothing;
  end if;
end $$;
