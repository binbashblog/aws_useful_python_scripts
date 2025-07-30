#!/usr/bin/env python3
import boto3
import csv

# Define your AWS profiles
aws_profiles = ["dev", "build", "test", "prod"]

# Initialize the CSV file
output_file = "unused_resources.csv"
header = ["Account", "Resource Type", "Resource ID", "Details"]

# Define functions to find unused resources
def find_unattached_elastic_ips(client):
    eips = client.describe_addresses()['Addresses']
    return [eip['AllocationId'] for eip in eips if 'AssociationId' not in eip]

def find_unused_security_groups(client):
    all_sgs = client.describe_security_groups()['SecurityGroups']
    unused_sgs = []
    for sg in all_sgs:
        if len(sg['IpPermissions']) == 0 and len(sg['IpPermissionsEgress']) == 0:
            unused_sgs.append(sg['GroupId'])
    return unused_sgs

def find_unused_volumes(client):
    volumes = client.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])['Volumes']
    return [vol['VolumeId'] for vol in volumes]

def find_unused_snapshots(client, account_id):
    snapshots = client.describe_snapshots(OwnerIds=[account_id])['Snapshots']
    return [snap['SnapshotId'] for snap in snapshots if snap.get('Description', '').startswith('Created by')]

def find_unused_amis(client):
    images = client.describe_images(Owners=['self'])['Images']
    unused_amis = []
    for image in images:
        instances = client.describe_instances(Filters=[
            {'Name': 'image-id', 'Values': [image['ImageId']]}
        ])['Reservations']
        if not instances:
            unused_amis.append(image['ImageId'])
    return unused_amis

def find_unused_key_pairs(client):
    key_pairs = client.describe_key_pairs()['KeyPairs']
    # Check for orphaned or unused key pairs (custom logic may vary)
    return [key['KeyName'] for key in key_pairs]

def find_unused_subnets(client):
    subnets = client.describe_subnets()['Subnets']
    unused_subnets = []
    for subnet in subnets:
        instances = client.describe_instances(Filters=[
            {'Name': 'subnet-id', 'Values': [subnet['SubnetId']]}
        ])['Reservations']
        if not instances:
            unused_subnets.append(subnet['SubnetId'])
    return unused_subnets

def find_unused_s3_buckets(s3_client):
    buckets = s3_client.list_buckets()['Buckets']
    unused_buckets = []
    for bucket in buckets:
        bucket_name = bucket['Name']
        try:
            last_accessed = s3_client.get_bucket_logging(Bucket=bucket_name)
            if not last_accessed:
                unused_buckets.append(bucket_name)
        except Exception as e:
            unused_buckets.append(bucket_name)  # Assume unused if access info isn't available
    return unused_buckets

def find_unused_vpns(client):
    vpns = client.describe_vpn_connections()['VpnConnections']
    unused_vpns = []
    for vpn in vpns:
        if vpn['State'] == 'available' and not vpn['Routes']:
            unused_vpns.append(vpn['VpnConnectionId'])
    return unused_vpns

# Process each account
with open(output_file, mode="w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(header)

    for profile in aws_profiles:
        session = boto3.Session(profile_name=profile)
        ec2_client = session.client("ec2")
        s3_client = session.client("s3")
        
        account_id = session.client("sts").get_caller_identity()["Account"]

        # Check for unused resources
        elastic_ips = find_unattached_elastic_ips(ec2_client)
        for eip in elastic_ips:
            writer.writerow([account_id, "Elastic IP", eip, "Unattached"])
        
        security_groups = find_unused_security_groups(ec2_client)
        for sg in security_groups:
            writer.writerow([account_id, "Security Group", sg, "No rules attached"])
        
        unused_volumes = find_unused_volumes(ec2_client)
        for volume in unused_volumes:
            writer.writerow([account_id, "EBS Volume", volume, "Available"])
        
        unused_snapshots = find_unused_snapshots(ec2_client, account_id)
        for snapshot in unused_snapshots:
            writer.writerow([account_id, "Snapshot", snapshot, "Unused"])
        
        unused_amis = find_unused_amis(ec2_client)
        for ami in unused_amis:
            writer.writerow([account_id, "AMI", ami, "No instances using it"])
        
        unused_key_pairs = find_unused_key_pairs(ec2_client)
        for key in unused_key_pairs:
            writer.writerow([account_id, "Key Pair", key, "Possibly unused"])
        
        unused_subnets = find_unused_subnets(ec2_client)
        for subnet in unused_subnets:
            writer.writerow([account_id, "Subnet", subnet, "No instances running in subnet"])
        
        unused_buckets = find_unused_s3_buckets(s3_client)
        for bucket in unused_buckets:
            writer.writerow([account_id, "S3 Bucket", bucket, "No access logs or unused"])
        
        unused_vpns = find_unused_vpns(ec2_client)
        for vpn in unused_vpns:
            writer.writerow([account_id, "VPN", vpn, "No active routes or usage"])

print(f"Unused resources report generated: {output_file}")
