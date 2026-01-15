-- Fix für Supabase Security Warning: function_search_path_mutable
-- Die Funktion get_current_user_id braucht einen festen search_path

CREATE OR REPLACE FUNCTION public.get_current_user_id()
RETURNS INTEGER
LANGUAGE SQL
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
    SELECT id FROM public.users WHERE email = auth.email() LIMIT 1;
$$;

-- Berechtigungen erneut setzen (für den Fall)
GRANT EXECUTE ON FUNCTION public.get_current_user_id() TO authenticated;
