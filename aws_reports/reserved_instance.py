#!/usr/bin/python

import boto3
import sys
import argparse
from collections import defaultdict

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Check unused reserved instances and unreserved running instances.")
parser.add_argument(
    "--profile", 
    type=str, 
    help="AWS profile to use (default is 'default')", 
    default="default"
)
args = parser.parse_args()

# Use the specified AWS profile
session = boto3.Session(profile_name=args.profile)
ec2_client = session.client("ec2")

# Get all running instances
reservations = ec2_client.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])

running_instances = defaultdict(int)
instance_mapping = defaultdict(list)  # Track instance IDs per type

for reservation in reservations["Reservations"]:
    for instance in reservation["Instances"]:
        if "SpotInstanceRequestId" in instance:
            sys.stderr.write(f"Disqualifying instance {instance['InstanceId']}: spot\n")
        else:
            instance_type = instance["InstanceType"]
            region = instance["Placement"]["AvailabilityZone"][:-1]  # Extract region (e.g., 'eu-west-1a' -> 'eu-west-1')
            
            running_instances[(instance_type, region)] += 1
            instance_mapping[(instance_type, region)].append(instance["InstanceId"])

# Get all reserved instances
reserved_instances = defaultdict(int)
reservations = ec2_client.describe_reserved_instances(Filters=[{"Name": "state", "Values": ["active"]}])

for reserved_instance in reservations["ReservedInstances"]:
    instance_type = reserved_instance["InstanceType"]

    # Extract region correctly
    if "AvailabilityZone" in reserved_instance and reserved_instance["AvailabilityZone"]:
        region = reserved_instance["AvailabilityZone"][:-1]  # Remove last character (AZ letter)
    elif "Scope" in reserved_instance and reserved_instance["Scope"] == "Region":
        region = session.region_name  # Use AWS session's region for regional reservations
    else:
        region = "Unknown"

    reserved_instances[(instance_type, region)] += reserved_instance["InstanceCount"]

# Compute instance differences
instance_diff = {x: reserved_instances[x] - running_instances.get(x, 0) for x in reserved_instances}

# Handling instances that are running but not reserved
for placement_key in running_instances:
    if placement_key not in reserved_instances:
        instance_diff[placement_key] = -running_instances[placement_key]

# Unused reservations
unused_reservations = {key: value for key, value in instance_diff.items() if value > 0}
if unused_reservations:
    for key, value in unused_reservations.items():
        print(f"UNUSED RESERVATION! ({value}) {key[0]} {key[1]}")
else:
    print("Congratulations, you have no unused reservations")

# Unreserved instances
unreserved_instances = {key: -value for key, value in instance_diff.items() if value < 0}
if unreserved_instances:
    for key, value in unreserved_instances.items():
        print(f"Instance not reserved: ({value}) {key[0]} {key[1]}")
else:
    print("Congratulations, you have no unreserved instances")

# Used reservations with instance names
used_reservations = {key: value for key, value in instance_diff.items() if value == 0}
if used_reservations:
    print("\nUsed Reservations:")
    for key, value in used_reservations.items():
        instance_list = instance_mapping.get(key, ["N/A"])
        print(f"Reserved Instances ({key[0]} {key[1]}): {', '.join(instance_list)}")
else:
    print("\nNo used reservations found")

# Summary
qty_running_instances = sum(running_instances.values())
qty_reserved_instances = sum(reserved_instances.values())

print(f"\n({qty_running_instances}) running on-demand instances\n({qty_reserved_instances}) reservations")

