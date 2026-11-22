"""
Admin routers that every service with Redis streams can mount (needs the `fastapi` and
`redis` extras):

- `make_streams_router`: the dead-letter queues of the streams the service reads (list,
  replay, discard) and an overview of the streams and their consumer groups.
- `make_resync_router`: the resync jobs of the service, run in the background.

The service passes its own admin authorization (`dependencies=[Security(get_auth, ...)]`):
nothing here decides who is an admin.
"""
