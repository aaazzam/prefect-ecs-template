"""Standalone test of the work pool base job template configuration logic."""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

# Work around macOS Python missing local certs (not needed in Lambda)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

API_KEY = "pnu_g5q60Wuqho7SSBvY6uInnff3WQc8Mt202UWW"
API_URL = "https://api.prefect.cloud/api/accounts/d6fe405d-87ae-4110-8393-d8488b9f2d94/workspaces/ea24c130-7e8b-4176-8c33-47ad68029b9e"
WORK_POOL_NAME = "ecs-test-pool-5"

# Placeholder ARNs matching what CloudFormation would produce
PROPS = {
    "ClusterArn": "arn:aws:ecs:us-east-1:123456789012:cluster/ecs-test-pool-cluster",
    "VpcId": "vpc-0abc123def456789a",
    "ExecutionRoleArn": "arn:aws:iam::123456789012:role/ecs-test-pool-TaskExecutionRole-XXXX",
    "TaskRoleArn": "arn:aws:iam::123456789012:role/ecs-test-pool-TaskRole-XXXX",
    "SubnetIds": ["subnet-0aaa111bbb222ccc3", "subnet-0ddd444eee555fff6"],
    "SecurityGroupId": "sg-0abc123def456789a",
    "LogGroupName": "/ecs/ecs-test-pool-abcde1234",
    "Region": "us-east-1",
}


def prefect_request(method, url, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
        if resp.status == 204:
            return None
        return json.loads(resp.read().decode())


def get_default_template(api_url, pool_type="ecs"):
    """Fetch the default base job template for a work pool type."""
    types_url = f"{api_url}/collections/work_pool_types"
    data = prefect_request("GET", types_url)
    for collection in data.values():
        if pool_type in collection:
            tpl = collection[pool_type].get("default_base_job_configuration", {})
            if tpl:
                return tpl
    raise ValueError(f"No default template found for pool type '{pool_type}'")


def set_variable_defaults(template, props):
    """Set defaults on the template's variables from stack resource properties."""
    vp = template.get("variables", {}).get("properties", {})
    defaults = {
        "cluster": props["ClusterArn"],
        "vpc_id": props["VpcId"],
        "execution_role_arn": props["ExecutionRoleArn"],
        "task_role_arn": props["TaskRoleArn"],
        "launch_type": "FARGATE",
        "configure_cloudwatch_logs": True,
        "cloudwatch_logs_options": {
            "awslogs-group": props["LogGroupName"],
            "awslogs-region": props["Region"],
            "awslogs-stream-prefix": "ecs",
        },
        "network_configuration": {
            "awsvpcConfiguration": {
                "subnets": props["SubnetIds"],
                "securityGroups": [props["SecurityGroupId"]],
                "assignPublicIp": "DISABLED",
            }
        },
    }
    for key, value in defaults.items():
        if key in vp:
            vp[key]["default"] = value
        else:
            print(f"  WARNING: Variable '{key}' not found in template schema")


def main():
    encoded_pool = urllib.parse.quote(WORK_POOL_NAME, safe="")
    pool_url = f"{API_URL}/work_pools/{encoded_pool}"
    pools_url = f"{API_URL}/work_pools/"

    print("Fetching default ECS template from collections API...")
    default_template = get_default_template(API_URL)
    print(f"  Got template with {len(default_template.get('variables', {}).get('properties', {}))} variables")

    # Simulate Create: create the pool with template
    print(f"\nCreating work pool '{WORK_POOL_NAME}' with configured template...")
    set_variable_defaults(default_template, PROPS)
    try:
        result = prefect_request("POST", pools_url, data={
            "name": WORK_POOL_NAME,
            "type": "ecs",
            "base_job_template": default_template,
        })
        print(f"  Created. Pool ID: {result.get('id')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 409:
            print("  Work pool already exists, will update instead.")
            # Simulate Update path
            pool = prefect_request("GET", pool_url)
            template = pool.get("base_job_template", {})
            if not template.get("variables", {}).get("properties"):
                print("  Existing template is empty, using default")
                template = default_template
            set_variable_defaults(template, PROPS)
            prefect_request("PATCH", pool_url, data={"base_job_template": template})
            print("  Updated.")
        else:
            print(f"  Create failed ({e.code}): {body[:500]}")
            return

    # Verify
    print(f"\n--- Verification ---")
    pool = prefect_request("GET", pool_url)
    bjt = pool.get("base_job_template", {})
    vp = bjt.get("variables", {}).get("properties", {})
    for key in ["cluster", "vpc_id", "execution_role_arn", "task_role_arn",
                "launch_type", "configure_cloudwatch_logs",
                "cloudwatch_logs_options", "network_configuration"]:
        val = vp.get(key, {}).get("default")
        if isinstance(val, dict):
            print(f"  {key}: {json.dumps(val, indent=4)}")
        else:
            print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
