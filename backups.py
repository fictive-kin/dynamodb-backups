# -*- coding: utf-8 -*-

import boto3
import hjson
import logging
import os
import pytz
import re

from copy import deepcopy
from datetime import datetime, timedelta
from flask import Flask
from manager import Manager

BASE_PATH = os.path.dirname(__file__)

ASSUME_ROLE_POLICY = {
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}

BACKUP_RETENTION = os.environ.get('BACKUP_RETENTION_IN_DAYS', 7)
TABLE_PATTERN = os.environ.get('TABLE_PATTERN', '.*')


logger = logging.getLogger(__name__)

# In case we're called as an HTTP request, handle gracefully
app = Flask(__name__)
manager = Manager()
dynamo = boto3.client('dynamodb')


@app.route('/')
def index():
    return 'Nothing to see here. You can go about your business. Move along.', 200


@manager.command
def cli_run(dry_run=False, backup_retention=None, table_pattern=None):
    """
    Invokes the backup run
    """
    kwargs = {}
    if dry_run:
        kwargs['dry_run'] = dry_run

    if backup_retention:
        kwargs['backup_retention'] = backup_retention

    if table_pattern:
        kwargs['table_pattern'] = table_pattern

    run(**kwargs)


def run(*args, **kwargs):
    backup_retention = kwargs.get('backup_retention', BACKUP_RETENTION)
    retention_cutoff = datetime.utcnow() - timedelta(days=int(backup_retention))
    retention_cutoff = retention_cutoff.replace(tzinfo=pytz.UTC)

    table_pattern = kwargs.get('table_pattern', TABLE_PATTERN)
    table_pattern = re.compile(table_pattern)

    dry_run = kwargs.get('dry_run', False)

    backup_count = 0
    paginator = dynamo.get_paginator('list_tables')
    for page in paginator.paginate():
        for record in page['TableNames']:
            if table_pattern.search(record) is None:
                logger.info('Skipping {} because of TABLE_PATTERN: {}'.format(record, TABLE_PATTERN))
                continue

            logger.debug('Creating backup of: {}'.format(record))
            backup_name = '{}-{}'.format(record, datetime.utcnow())
            if not dry_run:
                dynamo.create_backup(
                    TableName=record,
                    BackupName=backup_name.replace(' ', '-').replace('.', '-').replace(':', '-')
                )
            backup_count += 1
            backups = dynamo.list_backups(TableName=record)
            for backup_record in backups['BackupSummaries']:
                utc_dt = backup_record['BackupCreationDateTime'].replace(tzinfo=pytz.UTC)
                if utc_dt < retention_cutoff:
                    logger.debug('Removing old backup: {}'.format(backup_record['BackupArn']))
                    if not dry_run:
                        dynamo.delete_backup(BackupArn=backup_record['BackupArn'])

    if dry_run:
        logger.info('Would have run {} backups'.format(backup_count))
    else:
        logger.info('Ran {} backups'.format(backup_count))


@manager.command
def update_iam_role(stage):
    """
    Given a Zappa stage name, create/update the IAM role that is supposed to be
    used in the deployment
    """

    zappa_settings = {}
    with open(os.path.join(BASE_PATH, 'zappa_settings.json'), 'r') as zappa:
        zappa_settings = hjson.load(zappa)

    if stage not in zappa_settings:
        raise Exception('Stage does not exist: {}'.format(stage))

    role_name = _get_zappa_value(zappa_settings, stage, 'role_name')
    zappa_bucket = _get_zappa_value(zappa_settings, stage, 's3_bucket')
    events = _get_zappa_value(zappa_settings, stage, 'events')
    aws_account_id = boto3.client('sts').get_caller_identity().get('Account')

    iam_policy = {}
    with open(os.path.join(BASE_PATH, 'iam.zappa-role.json'), 'r') as role:
        iam_policy = hjson.load(role)

    statements = deepcopy(iam_policy['Statement'])
    iam_policy.update({'Statement': []})
    for statement in statements:
        resources = deepcopy(statement['Resource'])
        statement.update({'Resource': []})
        for resource in resources:
            try:
                resource = resource.format(zappa_bucket=zappa_bucket, role_name=role_name, AWS_ACCOUNT_ID=aws_account_id)
            except KeyError:
                pass
            statement['Resource'].append(resource)
        iam_policy['Statement'].append(statement)

    iam = boto3.client('iam')
    try:
        iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        print('Role does not exist, creating: {}'.format(role_name))
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=hjson.dumpsJSON(ASSUME_ROLE_POLICY)
        )

    resp = iam.put_role_policy(
        RoleName=role_name,
        PolicyName='zappa-permissions',
        PolicyDocument=hjson.dumpsJSON(iam_policy)
    )
    print('IAM policy has been updated.')


def _get_zappa_value(zappa_settings, stage, key):
    if key in zappa_settings[stage]:
        return zappa_settings[stage][key]

    if 'extends' in zappa_settings[stage]:
        return _get_zappa_value(zappa_settings, zappa_settings[stage]['extends'], key)
    else:
        raise Exception('{} has been configured for this stage'.format(key))


if __name__ == '__main__':
    manager.main()
