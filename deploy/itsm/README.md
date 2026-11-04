# BK-Lite ITSM runtime

This directory runs the unmodified official Flowable REST image and its own PostgreSQL database. Django owns ITSM business data and calls Flowable only through HTTP; it never reads or writes Flowable database tables.

All components used by this MVP are available without commercial license fees: Flowable OSS, PostgreSQL, Django, React, Ant Design, React Flow, and JSON Schema.

## Start Flowable

1. Copy `.env.example` to `.env` and replace both password placeholders with independent random values.
2. Start the stack:

   ```bash
   docker compose --env-file deploy/itsm/.env -f deploy/itsm/compose.yaml up -d
   ```

3. Inject the following values into the BK-Lite server runtime. Do not put credentials in the URL or commit the real values:

   ```text
   INSTALL_APPS=...,itsm
   FLOWABLE_REST_URL=http://flowable-rest:8080/flowable-rest/service
   FLOWABLE_REST_USER=rest-admin
   FLOWABLE_REST_PASSWORD=<same secret as the Flowable container>
   ```

If the BK-Lite server is outside the Compose network, use `http://127.0.0.1:18091/flowable-rest/service` instead. Keep the REST port bound to loopback or a private service network.

The Flowable REST container is intentionally not a startup dependency of the BK-Lite web process. When Flowable is unavailable, local service publishing and ticket commands remain persisted and the independent `itsm_dispatcher` retries them with bounded backoff. Human approval waits do not occupy Celery workers.

## Verify the engine contract

After Flowable is ready, run the real-engine verifier from the BK-Lite server environment:

```bash
python manage.py verify_itsm_flowable
```

The verifier deploys a uniquely named process and exercises serial approval, parallel countersign, before-sign, after-sign, handling, and completion through the official REST API. A zero exit code is required before upgrading the pinned Flowable image.

For a one-shot dispatcher check:

```bash
python manage.py itsm_dispatch --once --batch-size 20
```

## Resource and recovery policy

- Flowable REST is limited to 640 MiB with a 384 MiB Java heap. PostgreSQL is limited to 512 MiB. These are MVP starting values, not a claim of zero additional memory.
- The dispatcher is a normal Django management process managed by Supervisor. It is included only when `itsm` is present in `INSTALL_APPS`.
- A connection failure before request delivery clears the send marker and is retryable. An ambiguous response is reconciled by deployment name, ticket business key, or the unique task receipt variable before another side effect is attempted.
- Commands that reach their retry limit remain visible as `FAILED`; the dispatcher does not silently create a new process or switch to a different task ID.
- Back up the Flowable PostgreSQL volume and the BK-Lite business database independently. Restore both to a mutually consistent time and then allow the dispatcher to reconcile outstanding commands.

## Upgrade order

1. Back up both databases and record the current image tag/digest.
2. Run `verify_itsm_flowable` against the candidate image in an isolated database.
3. Stop the ITSM dispatcher, then stop Flowable REST. Do not stop the main BK-Lite web service merely because Flowable is offline.
4. Upgrade Flowable and let its supported database migration finish.
5. Run the verifier again, start the dispatcher, and check pending, uncertain, and failed command counts.
6. Keep the previous image and database backup until existing in-flight tickets complete successfully.
