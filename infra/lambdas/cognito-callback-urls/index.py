"""Web UI callback/logout URLs on the Cognito WebClient — CDK Custom Resource handler.

AuthStack owns the WebClient. WebUiStack sets the callback and logout URLs here
because AuthStack cannot know the CloudFront URL without a circular dependency.

UpdateUserPoolClient resets every field the call leaves out to its default. So
the handler reads the client and sends every field back unchanged (OAuth scopes,
OAuth flows, auth flows, token validity, ...) except CallbackURLs and LogoutURLs.
"""

import json
import logging

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cognito = boto3.client("cognito-idp")

# urllib3 is bundled with botocore in Lambda — no extra dependency needed.
_http = urllib3.PoolManager()


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


def set_urls(props):
    current = cognito.describe_user_pool_client(
        UserPoolId=props["UserPoolId"], ClientId=props["ClientId"],
    )["UserPoolClient"]
    update_fields = set(
        cognito.meta.service_model.operation_model("UpdateUserPoolClient").input_shape.members
    )
    request = update_request(current, props["CallbackURLs"], props["LogoutURLs"], update_fields)
    logger.info(
        "Updating client %s: CallbackURLs=%s LogoutURLs=%s, keeping AllowedOAuthScopes=%s",
        props["ClientId"], request["CallbackURLs"], request["LogoutURLs"],
        request.get("AllowedOAuthScopes"),
    )
    cognito.update_user_pool_client(**request)


def handler(event, context):
    logger.info("Event: %s", json.dumps(event, default=str))
    props = event["ResourceProperties"]
    physical_id = f"cognito-callback-urls:{props['ClientId']}"
    try:
        if event["RequestType"] in ("Create", "Update"):
            set_urls(props)
        # Delete leaves the client as it is: AuthStack owns it.
        send(event, context, "SUCCESS", physical_id)
    except Exception as e:
        logger.exception("Failed")
        send(event, context, "FAILED", physical_id, reason=str(e))
