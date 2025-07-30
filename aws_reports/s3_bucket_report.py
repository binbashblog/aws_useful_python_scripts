#!/usr/bin/env python3

import boto3
import os
import pandas as pd
import threading
import sys
import time
from botocore.exceptions import BotoCoreError, NoCredentialsError, ClientError
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Spinner to indicate progress
class Spinner:
    def __init__(self):
        self.running = False
        self.spinner_thread = None

    def spin(self):
        while self.running:
            for char in "|/-\\":
                sys.stdout.write(f"\rProcessing... {char}")
                sys.stdout.flush()
                if not self.running:
                    break
                time.sleep(0.1)

    def start(self):
        self.running = True
        self.spinner_thread = threading.Thread(target=self.spin)
        self.spinner_thread.start()

    def stop(self):
        self.running = False
        if self.spinner_thread:
            self.spinner_thread.join()
        sys.stdout.write("\rDone!           \n")

def get_bucket_creator(cloudtrail_client, bucket_name):
    """Retrieve the creator of an S3 bucket using CloudTrail logs."""
    try:
        event_time = datetime.now(timezone.utc) - timedelta(days=90)
        response = cloudtrail_client.lookup_events(
            LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": bucket_name}],
            StartTime=event_time,
            MaxResults=5
        )
        for event in response.get("Events", []):
            return event.get("Username", "Unknown")
    except (BotoCoreError, ClientError):
        pass
    return "Unknown"

def get_largest_files(s3_client, bucket_name, region):
    """Retrieve the largest files in an S3 bucket."""
    try:
        files = []
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get("Contents", []):
                files.append((obj["Key"], obj["Size"], obj["LastModified"]))
        
        largest_files = sorted(files, key=lambda x: x[1], reverse=True)[:10]
        
        # Get file owner using S3 object ACL
        file_info = []
        for key, size, last_modified in largest_files:
            try:
                acl = s3_client.get_object_acl(Bucket=bucket_name, Key=key)
                owner = acl.get("Owner", {}).get("DisplayName", "Unknown")
            except ClientError:
                owner = "Unknown"
            file_info.append((key, size, last_modified, owner))
        
        return file_info
    except (BotoCoreError, ClientError):
        return []

def process_account(profile):
    """Process an AWS profile to retrieve S3 bucket details."""
    session = boto3.Session(profile_name=profile)
    s3_client = session.client("s3")
    cloudtrail_client = session.client("cloudtrail")

    try:
        response = s3_client.list_buckets()
        buckets = response.get("Buckets", [])
    except (NoCredentialsError, BotoCoreError, ClientError):
        print(f"Failed to access S3 for profile {profile}")
        return None

    data = []
    largest_files_data = []
    
    for bucket in buckets:
        bucket_name = bucket["Name"]
        try:
            location = s3_client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint", "us-east-1")
            creator = get_bucket_creator(cloudtrail_client, bucket_name)

            total_size = 0
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get("Contents", []):
                    total_size += obj["Size"]

            data.append([bucket_name, location, total_size, creator])

            # Get largest files
            largest_files = get_largest_files(s3_client, bucket_name, location)
            for key, size, last_modified, owner in largest_files:
                largest_files_data.append([bucket_name, key, size, last_modified, owner])

        except ClientError as e:
            print(f"Skipping bucket {bucket_name}: {e}")

    return data, largest_files_data

def main():
    """Main function to run the script."""
    spinner = Spinner()
    spinner.start()

    boto3_session = boto3.Session()
    profiles = boto3_session.available_profiles

    if "default" in profiles:
        profiles.remove("default")
        profiles.insert(0, "default")  # Ensure 'default' profile runs first

    writer = pd.ExcelWriter("s3_bucket_report.xlsx", engine="xlsxwriter")

    for profile in profiles:
        print(f"=== Checking AWS Profile: {profile} ===")

        result = process_account(profile)
        if result is None:
            continue

        bucket_data, file_data = result

        # Write bucket info
        df_buckets = pd.DataFrame(bucket_data, columns=["Bucket Name", "Region", "Total Size (Bytes)", "Creator"])
        df_buckets.to_excel(writer, sheet_name=f"{profile}_buckets", index=False)

        # Write file info
        df_files = pd.DataFrame(file_data, columns=["Bucket Name", "File Key", "Size (Bytes)", "Last Modified", "Owner"])
        df_files.to_excel(writer, sheet_name=f"{profile}_files", index=False)

    writer.close()
    spinner.stop()
    print("Report saved: s3_bucket_report.xlsx")

if __name__ == "__main__":
    main()

