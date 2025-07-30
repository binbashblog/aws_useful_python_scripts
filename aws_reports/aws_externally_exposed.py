#!/usr/bin/env python3
import boto3
import pandas as pd
import os
import configparser
import concurrent.futures
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
from botocore.config import Config

# AWS Config for retries and timeouts
BOTO3_CONFIG = Config(retries={'max_attempts': 5}, connect_timeout=5, read_timeout=5)

def get_aws_profiles():
    """Retrieve AWS profiles from ~/.aws/config"""
    profiles = ['default']
    config = configparser.ConfigParser()
    config_file = os.path.expanduser('~/.aws/config')

    if os.path.exists(config_file):
        config.read(config_file)
        profiles.extend([section.replace('profile ', '') for section in config.sections() if section.startswith('profile ')])

    return list(set(profiles))

def get_regions(session):
    """Get available AWS regions."""
    try:
        ec2 = session.client('ec2', config=BOTO3_CONFIG)
        return [region['RegionName'] for region in ec2.describe_regions()['Regions']]
    except (ClientError, NoCredentialsError, EndpointConnectionError) as e:
        print(f"Error fetching regions: {e}")
        return []

def get_exposed_security_groups(session, region):
    """Find security groups allowing 0.0.0.0/0"""
    try:
        ec2 = session.client('ec2', region_name=region, config=BOTO3_CONFIG)
        security_groups = ec2.describe_security_groups()['SecurityGroups']
        return [
            ['Security Group', sg['GroupId'], sg.get('GroupName', 'N/A'), 'Allows 0.0.0.0/0', region]
            for sg in security_groups
            for rule in sg.get('IpPermissions', [])
            for ip in rule.get('IpRanges', [])
            if ip.get('CidrIp') == '0.0.0.0/0'
        ]
    except ClientError as e:
        print(f"Error fetching security groups in {region}: {e}")
        return []

def get_exposed_network_acls(session, region):
    """Find Network ACLs allowing unrestricted access but ignore overridden allow rules"""
    try:
        ec2 = session.client('ec2', region_name=region, config=BOTO3_CONFIG)
        network_acls = ec2.describe_network_acls()['NetworkAcls']
        results = []

        for nacl in network_acls:
            allow_rules = {}
            deny_rules = set()

            for entry in nacl.get('Entries', []):
                cidr = entry.get('CidrBlock', entry.get('Ipv6CidrBlock'))
                action = entry.get('RuleAction')
                rule_number = entry.get('RuleNumber')

                if action == 'deny':
                    deny_rules.add(cidr)  # Store deny rules
                elif action == 'allow':
                    allow_rules[cidr] = rule_number  # Store allow rules with rule number

            for cidr, rule_number in allow_rules.items():
                if cidr not in deny_rules:  # Only add if no deny rule exists
                    results.append(['Network ACL', nacl['NetworkAclId'], 'N/A', f'Allows {cidr}', region])

        return results
    except ClientError as e:
        print(f"Error fetching network ACLs in {region}: {e}")
        return []

def get_exposed_ec2_instances(session, region):
    """Find EC2 instances with public IPs"""
    try:
        ec2 = session.client('ec2', region_name=region, config=BOTO3_CONFIG)
        instances = ec2.describe_instances()['Reservations']
        return [
            ['EC2 Instance', instance['InstanceId'], 'N/A', f'Public IP: {instance["PublicIpAddress"]}', region]
            for reservation in instances
            for instance in reservation['Instances']
            if 'PublicIpAddress' in instance
        ]
    except ClientError as e:
        print(f"Error fetching EC2 instances in {region}: {e}")
        return []

def get_exposed_s3_buckets(session):
    """Find S3 buckets with public access"""
    try:
        s3 = session.client('s3', config=BOTO3_CONFIG)
        buckets = s3.list_buckets()['Buckets']
        results = []
        for bucket in buckets:
            bucket_name = bucket['Name']
            try:
                acl = s3.get_public_access_block(Bucket=bucket_name)
                config = acl.get('PublicAccessBlockConfiguration', {})
                if not config.get('BlockPublicAcls', True) or not config.get('RestrictPublicBuckets', True):
                    results.append(['S3 Bucket', bucket_name, 'N/A', 'Public Access Enabled', 'Global'])
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchPublicAccessBlockConfiguration':
                    results.append(['S3 Bucket', bucket_name, 'N/A', 'No Public Access Block Config', 'Global'])
        return results
    except ClientError as e:
        print(f"Error fetching S3 buckets: {e}")
        return []

def process_region(session, region):
    """Process a single AWS region"""
    return (
        get_exposed_security_groups(session, region)
        + get_exposed_network_acls(session, region)
        + get_exposed_ec2_instances(session, region)
    )

def process_profile(profile):
    """Process AWS resources for a specific profile"""
    print(f"Processing profile: {profile}")
    session = boto3.Session(profile_name=profile)
    regions = get_regions(session)
    data = []

    # Parallelize per-region checks
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = executor.map(lambda r: process_region(session, r), regions)
        for result in results:
            data.extend(result)

    # Add S3 buckets (global service, no need for region loop)
    data.extend(get_exposed_s3_buckets(session))

    return profile, data

def write_to_excel(filename='aws_externally_exposed_objects.xlsx'):
    """Write results to an Excel file with each profile in a separate sheet, ensuring text wraps."""
    profiles = get_aws_profiles()
    writer = pd.ExcelWriter(filename, engine='xlsxwriter')

    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = executor.map(process_profile, profiles)
        for profile, data in results:
            df = pd.DataFrame(data, columns=['Resource Type', 'Resource ID', 'Resource Name', 'Issue', 'Region'])
            df.to_excel(writer, sheet_name=profile[:31], index=False)

            # Get the workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets[profile[:31]]

            # Define a wrap text format
            wrap_format = workbook.add_format({'text_wrap': True})

            # Set column widths and apply wrap format
            worksheet.set_column('A:A', 15, wrap_format)  # Resource Type
            worksheet.set_column('B:B', 30, wrap_format)  # Resource ID
            worksheet.set_column('C:C', 30, wrap_format)  # Resource Name
            worksheet.set_column('D:D', 50, wrap_format)  # Issue
            worksheet.set_column('E:E', 15, wrap_format)  # Region

    writer.close()
    print(f"Report saved to {filename}")

if __name__ == '__main__':
    write_to_excel()

