-- Enable RLS for mileage_trips table
-- Run this in Supabase SQL Editor

-- Enable RLS
ALTER TABLE public.mileage_trips ENABLE ROW LEVEL SECURITY;

-- Create policy for authenticated users
CREATE POLICY "Users can manage own mileage trips" ON public.mileage_trips
    FOR ALL TO authenticated
    USING (user_id = public.get_current_user_id())
    WITH CHECK (user_id = public.get_current_user_id());
