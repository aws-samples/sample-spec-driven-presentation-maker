"""Callback/logout URLs on the Cognito WebClient — CDK Custom Resource handler.

AuthStack deploys this function and owns the URL set: exactly the dev URL
(DEV_URL) and the Web UI CloudFront site URL that WebUiStack publishes in SSM
(SITE_URL_PARAM). AuthStack cannot reference the CloudFront URL directly (that
would be a circular dependency), so its template holds the dev URL only, and
CloudFormation writes that list every time it updates the client. Two custom
resources run this function: AuthStack's after every change to the client, and
WebUiStack's when the site URL is created or changes. Their properties only
decide when CloudFormation calls; the function reads the URL set from its own
configuration and SSM, so every call writes the same set.

UpdateUserPoolClient resets every field the call leaves out to its default. So
the handler reads the client and sends every field back unchanged (OAuth scopes,
OAuth flows, auth flows, token validity, ...) except CallbackURLs and LogoutURLs.
"""

import json
import logging
import os
import re

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cognito = boto3.client("cognito-idp")
ssm = boto3.client("ssm")

# urllib3 is bundled with botocore in Lambda — no extra dependency needed.
_http = urllib3.PoolManager()

# WebUiStack's site URL is always its CloudFront distribution's domain name.
_SITE_URL_RE = re.compile(r"^https://[a-z0-9]+\.cloudfront\.net$")


def send(event, context, status, physical_id, reason=None):
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch Log Stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": {},
    }).encode()
    url = event["ResponseURL"]
    if not url.startswith("https://"):
        raise ValueError("ResponseURL must be HTTPS")
    _http.request("PUT", url, body=body, headers={"Content-Type": ""})


def update_request(current, callback_urls, logout_urls, update_fields):
    """Return the UpdateUserPoolClient parameters for ``current`` with new URLs.

    ``current`` is DescribeUserPoolClient's ``UserPoolClient``. Every field that
    UpdateUserPoolClient accepts is copied; read-only fields (ClientSecret,
    CreationDate, ...) are dropped. Only the URLs are replaced.
    """
    request = {key: value for key, value in current.items() if key in update_fields}
    request["CallbackURLs"] = list(callback_urls)
    request["LogoutURLs"] = list(logout_urls)
    return request


def published_site_url():
    """Return the site URL WebUiStack published, or None before it has been deployed.

    Raises ValueError for a value that is not a CloudFront site URL, so nothing
    else can enter the allowlist through the parameter.
    """
    try:
        value = ssm.get_parameter(Name=os.environ["SITE_URL_PARAM"])["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None
    if not _SITE_URL_RE.match(value):
        raise ValueError(f"{os.environ['SITE_URL_PARAM']} is not a CloudFront site URL: {value!r}")
    return value


def set_urls():
    site_url = published_site_url()
    if site_url is None:
        # No Web UI yet: the template's dev URL is the whole set, and
        # CloudFormation already wrote it. Leave the client as it is.
        logger.info("No site URL in %s; leaving the client unchanged", os.environ["SITE_URL_PARAM"])
        return
    urls = [os.environ["DEV_URL"], site_url]
    current = cognito.describe_user_pool_client(
        UserPoolId=os.environ["USER_POOL_ID"], ClientId=os.environ["CLIENT_ID"],
    )["UserPoolClient"]
    if current.get("CallbackURLs") == urls and current.get("LogoutURLs") == urls:
        logger.info("Client %s already has CallbackURLs=LogoutURLs=%s", os.environ["CLIENT_ID"], urls)
        return
    update_fields = set(
        cognito.meta.service_model.operation_model("UpdateUserPoolClient").input_shape.members
    )
    request = update_request(current, urls, urls, update_fields)
    # Log only the URLs: ``request`` derives from the described client, which
    # can carry ClientSecret.
    logger.info("Updating client %s: CallbackURLs=LogoutURLs=%s", os.environ["CLIENT_ID"], urls)
    cognito.update_user_pool_client(**request)


def handler(event, context):
    logger.info("Event: %s", json.dumps(event, default=str))
    physical_id = f"web-client-urls:{os.environ['CLIENT_ID']}"
    try:
        if event["RequestType"] in ("Create", "Update"):
            set_urls()
        # Delete leaves the client as it is: AuthStack owns it.
        send(event, context, "SUCCESS", physical_id)
    except Exception as e:
        logger.exception("Failed")
        send(event, context, "FAILED", physical_id, reason=str(e))
