# Programmatic client (reference)

`sdpm_client.py` creates decks on an SDPM Cloud deployment as the signed-in user, from a
script, cron job, AWS Lambda function or AWS Step Functions state machine. It is a single
file that uses only the documented contract; copy it into your own project.

Turn on `auth.programmaticClient` in `infra/config.yaml` and deploy first. The full guide
(settings, the contract, a Lambda + Step Functions example, security notes) is
[Programmatic Access](../../docs/en/programmatic-access.md)
([日本語](../../docs/ja/programmatic-access.md)).

```bash
# once, in a browser (listens on 127.0.0.1:8765 for the one redirect)
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <ProgrammaticClientId>
# or keep the refresh token in AWS Secrets Manager instead of a local 0600 file
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <ProgrammaticClientId> \
  --store secretsmanager:sdpm/my-bot

# unattended
uv run sdpm_client.py run "Make a 3-slide deck about ... Do not ask questions."
uv run sdpm_client.py status <sessionId>
```

Every command prints one JSON object. Exit codes: `0` done, `1` error, `2` usage, `3` the
refresh token is expired, revoked or invalid (run `login` again).

`tests/test_programmatic_client.py` covers the session id rule, the loopback-only listener,
the token file mode and the exit code for a refused refresh token.
