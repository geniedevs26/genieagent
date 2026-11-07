-- The suppression guard is a trigger function and must not be callable through
-- the exposed PostgREST RPC surface by anon or authenticated users.
revoke execute on function public.block_suppressed_outreach() from public, anon, authenticated;
grant execute on function public.block_suppressed_outreach() to service_role;
