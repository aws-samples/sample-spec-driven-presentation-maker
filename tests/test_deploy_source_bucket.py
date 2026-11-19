# SPDX-License-Identifier: MIT-0
"""`scripts/deploy.sh` — the S3 bucket that carries the CodeBuild source.

The rules under test: the bucket name is in the S3 account regional namespace (``-an``);
every call against it except ``create-bucket`` passes ``--expected-bucket-owner``; a bucket
that is not owned by the account, or cannot be created in that namespace, stops the script
before anything is packaged or uploaded; a bucket the script creates gets Block Public
Access and a 7-day expiry, an existing bucket is left as it is.

The real script runs in an empty directory with a fake ``aws`` (answers from env vars,
logs every argv), a fake ``zip`` and a no-op ``sleep`` first on ``PATH``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"
ACCOUNT = "111122223333"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the fake aws is a script with a shebang")
pytestmark = POSIX_ONLY

HEAD_404 = "An error occurred (404) when calling the HeadBucket operation: Not Found"
HEAD_403 = "An error occurred (403) when calling the HeadBucket operation: Forbidden"

FAKE_AWS = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_AWS_LOG"], "a") as handle:
    handle.write(json.dumps(args) + "\\n")

def query():
    return args[args.index("--query") + 1] if "--query" in args else ""

cmd = args[:2]
if args[:1] == ["--version"]:
    print("aws-cli/2.0.0 Python/3.8.0 Linux/5.10 exe/x86_64")
elif cmd == ["sts", "get-caller-identity"]:
    print("{account}")
elif cmd == ["s3api", "head-bucket"]:
    head = os.environ["FAKE_AWS_HEAD"]
    if head == "200":
        print("{{}}")
    else:
        sys.stderr.write({head_errors}[head] + "\\n")
        sys.exit(254)
elif cmd == ["s3api", "create-bucket"]:
    create = os.environ["FAKE_AWS_CREATE"]
    if create == "unknown-option":
        sys.stderr.write("aws: [ERROR]: An error occurred (ParamValidation): Unknown options: --bucket-namespace, account-regional\\n")
        sys.exit(252)
    if create == "fail":
        sys.stderr.write("An error occurred (InvalidRequest) when calling the CreateBucket operation: not supported\\n")
        sys.exit(254)
    print("{{}}")
elif cmd in (["s3api", "put-public-access-block"], ["s3api", "put-bucket-lifecycle-configuration"],
             ["s3api", "put-object"], ["s3api", "head-object"], ["iam", "get-role"],
             ["codebuild", "update-project"]):
    pass
elif cmd == ["codebuild", "batch-get-projects"]:
    print("sdpm-deploy")
elif cmd == ["codebuild", "start-build"]:
    print("build-1")
elif cmd == ["codebuild", "batch-get-builds"]:
    print({{"builds[0].buildStatus": "SUCCEEDED", "builds[0].currentPhase": "COMPLETED"}}.get(query(), "None"))
elif cmd == ["cloudformation", "describe-stacks"]:
    pass
else:
    sys.exit(99)
"""

FAKE_ZIP = """#!{python}
import sys
open(sys.argv[2], "wb").write(b"PK")
"""


def run_deploy(tmp_path: Path, *, region: str = "ap-northeast-1", head: str = "404", create: str = "ok"):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "deploy.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {
        "aws": FAKE_AWS.format(
            python=sys.executable, account=ACCOUNT, head_errors=repr({"404": HEAD_404, "403": HEAD_403})
        ),
        "zip": FAKE_ZIP.format(python=sys.executable),
        "sleep": "#!/bin/sh\nexit 0\n",
    }
    for name, text in fakes.items():
        path = bin_dir / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "aws.log"
    log.touch()
    env = {k: v for k, v in os.environ.items() if k not in ("AWS_PROFILE", "AWS_DEFAULT_REGION")}
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        FAKE_AWS_LOG=str(log),
        FAKE_AWS_HEAD=head,
        FAKE_AWS_CREATE=create,
    )
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "deploy.sh"), "--region", region],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return proc, calls


def find(calls, *cmd):
    return [c for c in calls if c[: len(cmd)] == list(cmd)]


def value(call, flag):
    return call[call.index(flag) + 1]


def bucket(region: str) -> str:
    return f"sdpm-deploy-{ACCOUNT}-{region}-an"


def test_foreign_owner_stops_before_packaging(tmp_path):
    proc, calls = run_deploy(tmp_path, head="403")

    assert proc.returncode != 0
    assert bucket("ap-northeast-1") in proc.stderr
    assert f"not owned by account {ACCOUNT}" in proc.stderr
    assert "(403)" in proc.stderr
    assert "Nothing was uploaded" in proc.stderr
    assert "Packaging source" not in proc.stdout
    assert [c[:2] for c in calls] == [["sts", "get-caller-identity"], ["s3api", "head-bucket"]]
    assert value(calls[1], "--expected-bucket-owner") == ACCOUNT


def test_new_bucket_is_created_in_the_account_regional_namespace(tmp_path):
    proc, calls = run_deploy(tmp_path, head="404", create="ok")

    assert proc.returncode == 0, proc.stderr
    (create,) = find(calls, "s3api", "create-bucket")
    assert value(create, "--bucket") == bucket("ap-northeast-1")
    assert value(create, "--bucket-namespace") == "account-regional"
    assert value(create, "--create-bucket-configuration") == "LocationConstraint=ap-northeast-1"

    (bpa,) = find(calls, "s3api", "put-public-access-block")
    config = value(bpa, "--public-access-block-configuration")
    for setting in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"):
        assert f"{setting}=true" in config

    (lifecycle,) = find(calls, "s3api", "put-bucket-lifecycle-configuration")
    (rule,) = json.loads(value(lifecycle, "--lifecycle-configuration"))["Rules"]
    assert rule["Status"] == "Enabled"
    assert rule["Expiration"]["Days"] == 7
    assert rule["Filter"]["Prefix"] == "source/"

    (put,) = find(calls, "s3api", "put-object")
    assert value(put, "--key").startswith("source/")
    (start,) = find(calls, "codebuild", "start-build")
    assert value(start, "--source-location-override").startswith(bucket("ap-northeast-1") + "/source/")


def test_every_source_bucket_call_checks_the_owner(tmp_path):
    proc, calls = run_deploy(tmp_path, head="404", create="ok")

    assert proc.returncode == 0, proc.stderr
    assert not [c for c in calls if c[:1] == ["s3"]], "high-level aws s3 cannot check the bucket owner"
    s3api = [c for c in calls if c[:1] == ["s3api"]]
    assert {c[1] for c in s3api} == {
        "head-bucket",
        "create-bucket",
        "put-public-access-block",
        "put-bucket-lifecycle-configuration",
        "put-object",
        "head-object",
    }
    for call in s3api:
        assert value(call, "--bucket").endswith("-an")
        if call[1] != "create-bucket":
            assert value(call, "--expected-bucket-owner") == ACCOUNT, call
    assert not [c for c in calls if "--bucket" in c and not value(c, "--bucket").endswith("-an")]


def test_us_east_1_has_no_location_constraint(tmp_path):
    proc, calls = run_deploy(tmp_path, region="us-east-1", head="404", create="ok")

    assert proc.returncode == 0, proc.stderr
    (create,) = find(calls, "s3api", "create-bucket")
    assert value(create, "--bucket") == bucket("us-east-1")
    assert "--create-bucket-configuration" not in create


def test_existing_own_bucket_keeps_its_configuration(tmp_path):
    proc, calls = run_deploy(tmp_path, head="200")

    assert proc.returncode == 0, proc.stderr
    for cmd in ("create-bucket", "put-public-access-block", "put-bucket-lifecycle-configuration"):
        assert not find(calls, "s3api", cmd)
    assert find(calls, "s3api", "put-object")


def test_old_cli_stops_with_version_guidance(tmp_path):
    proc, calls = run_deploy(tmp_path, head="404", create="unknown-option")

    assert proc.returncode != 0
    assert "2.34.8" in proc.stderr
    assert "Nothing was uploaded" in proc.stderr
    assert "Packaging source" not in proc.stdout
    assert not find(calls, "s3api", "put-object")
    assert len(find(calls, "s3api", "create-bucket")) == 1


def test_create_failure_stops_without_fallback(tmp_path):
    proc, calls = run_deploy(tmp_path, head="404", create="fail")

    assert proc.returncode != 0
    assert "Bahrain" in proc.stderr and "UAE" in proc.stderr
    assert "InvalidRequest" in proc.stderr
    assert "Packaging source" not in proc.stdout
    assert not find(calls, "s3api", "put-object")
    assert len(find(calls, "s3api", "create-bucket")) == 1


@pytest.mark.parametrize("head", ["200", "404"])
def test_no_unexpected_aws_calls(tmp_path, head):
    proc, calls = run_deploy(tmp_path, head=head)

    assert proc.returncode == 0, proc.stderr
    assert "Deployment complete!" in proc.stdout
    known = {
        ("sts", "get-caller-identity"),
        ("s3api", "head-bucket"),
        ("s3api", "create-bucket"),
        ("s3api", "put-public-access-block"),
        ("s3api", "put-bucket-lifecycle-configuration"),
        ("s3api", "put-object"),
        ("s3api", "head-object"),
        ("iam", "get-role"),
        ("codebuild", "batch-get-projects"),
        ("codebuild", "update-project"),
        ("codebuild", "start-build"),
        ("codebuild", "batch-get-builds"),
        ("cloudformation", "describe-stacks"),
    }
    assert not [c for c in calls if tuple(c[:2]) not in known]
