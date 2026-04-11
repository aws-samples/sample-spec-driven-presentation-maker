"""CloudFront signing key provisioner — CDK Custom Resource handler."""

import json
import subprocess  # nosec B404 — openssl invocation with fixed args only
import logging

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")

_OPENSSL = "/usr/bin/openssl"

# urllib3 is bundled with botocore in Lambda — no extra dependency needed.
_http = urllib3.PoolManager()


def send(event, context, status, data=None, physical_id=None, reason=None):
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch Log Stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_id or event.get("PhysicalResourceId", context.log_stream_name),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode()
    url = event["ResponseURL"]
    if not url.startswith("https://"):
        raise ValueError("ResponseURL must be HTTPS")
    _http.request("PUT", url, body=body, headers={"Content-Type": ""})


def handler(event, context):
    logger.info("Event: %s", json.dumps(event, default=str))
    props = event["ResourceProperties"]
    priv_param = props["PrivateKeyParam"]
    pub_param = props["PublicKeyParam"]
    request_type = event["RequestType"]

    try:
        if request_type == "Create":
            priv_pem = subprocess.check_output(  # nosec B603 B607 — fixed args, no user input
                [_OPENSSL, "genrsa", "2048"], stderr=subprocess.DEVNULL,
            ).decode()
            pub_pem = subprocess.check_output(  # nosec B603 B607 — fixed args, no user input
                [_OPENSSL, "rsa", "-pubout"], input=priv_pem.encode(), stderr=subprocess.DEVNULL,
            ).decode()

            ssm.put_parameter(Name=priv_param, Value=priv_pem, Type="SecureString", Overwrite=True)
            ssm.put_parameter(Name=pub_param, Value=pub_pem, Type="String", Overwrite=True)

            send(event, context, "SUCCESS", data={"PublicKeyPem": pub_pem}, physical_id=priv_param)

        elif request_type == "Delete":
            for name in (priv_param, pub_param):
                try:
                    ssm.delete_parameter(Name=name)
                except ssm.exceptions.ParameterNotFound:
                    pass
            send(event, context, "SUCCESS", physical_id=priv_param)

        else:  # Update
            pub_pem = ssm.get_parameter(Name=pub_param)["Parameter"]["Value"]
            send(event, context, "SUCCESS", data={"PublicKeyPem": pub_pem}, physical_id=priv_param)

    except Exception as e:
        logger.exception("Failed")
        send(event, context, "FAILED", reason=str(e), physical_id=priv_param)
