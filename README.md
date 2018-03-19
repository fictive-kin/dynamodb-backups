
# Dynamo Backups

Ever "accidentally" deleted a DynamoDB table only to realize that you still needed it? Wouldn't it be nice if you had backups that you could restore from? Then this is your answer.

## Prerequisites:

- An AWS account with enough privileges to create a new IAM role
- A local clone of this repo
- And of course, DynamoDB tables that you want to have backed up


## Setup

The first thing you need to do is create a python virtual environment. You can do this by running `virtualenv <venv>` (or `python3 -m venv <venv>` for use with `python3`) where `<venv>` is the directory name you wish your new virtual environment to have.

Once you have created the virtual environment, you need to activate it, by running `source <venv>/bin/activate`. This is something you need to do everytime that you want to interact with your DynamoDB backup Lambda.

After activating your virtual environment, you need to install the required `pip` modules. This can be accomplished via `pip install -r requirements.txt` from the root of the repo.

Next thing is to adjust certain values in `zappa_settings.json` to match your settings:

```json
{
    "base": {
        "app_function": "backups.app",
        "project_name": "dynamo-backups",
        "s3_bucket": "<bucket-name>",
        "role_name": "<role-name>",
        "manage_roles": false,
        "cloudwatch_log_level": "DEBUG",
        // These tasks are not designed to respond to incoming HTTP events,
        // therefore we don't need the API Gateway nor the keep warm function
        "apigateway_enabled": false,
        "keep_warm": false,
        // These are crons, so, give them the max time to complete
        "timeout_seconds": 300,
    },
    "<stage-name>": {
        "extends": "base",
        "aws_environment_variables": {
            "TABLE_PATTERN": "<pattern>", // Regex pattern
            "BACKUP_RETENTION_IN_DAYS": "<num_days>", // Needs to be a string
        },
        "events": [
            {
                "function": "backups.run",
                "expression": "rate(1 day)"
            },
        ],
    }
}
```

- `<bucket-name>` should be an S3 bucket name that is not currently in use.
- `<role-name>` is the IAM role under which the backups will run.
- `<stage-name>` is what you will refer to when performing Zappa actions. You usually want this to be easy to remember, especially if you have multiple Lambdas running.
- `<pattern>` is the table matching pattern, the basic pattern should be `.*` unless you plan on having multiple backup runners with different retention periods for different sets of DynamoDB tables.
- `<num_days>` is the number of days before a backup will be deleted.

You can also modify any of the other values, adding extras as desired, according to the [Zappa docs](https://github.com/Miserlou/Zappa).

The next thing you want to do, is run `python ./backups update_iam_role <stage-name>` which will give the `<role-name>` that you specified the appropriate permissions to run the backups. It uses `iam.zappa-role.json` as it's template to create the role policy, therefore, if there are additional IAM permissions that you wish your Lambda to have, you can add them in and run it again. **Note**: if run additional times, it replaces the role policy that was previously there, so be aware.

## Running

In order to set it to run, you need to deploy the Lambda. You can do this, with your virtual environment activated, via `zappa deploy <stage-name>`. Zappa will do it's thing to setup what your Lambda needs to run in perpetuity and schedule it to be run, as per the `expression` in the stage's event settings.

If you make customizations to the code and wish to redeploy, or perhaps change the retention period, table pattern or frequency of invocation, then you need to update the deployment via `zappa update <stage-name>`. (Technically, if you only changed the frequency of invocation, you could run `zappa schedule <stage-name>` which will update only the scheduling.

Once you no longer need this backup solution, you can undeploy it with `zappa undeploy <stage-name>`.

## Considerations

Often times you will want to harness different stages for QA and production, because you don't typically need as frequent a backup of a QA table as you would want of a production table.


A [Fictive Kin](https://fictivekin.com) Creation
