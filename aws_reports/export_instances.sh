#!/bin/bash

output_file="ec2_instances_report.csv"

# Write CSV headers
echo "Profile,Region,InstanceId,InstanceType,State,Name" > "$output_file"

# Get all AWS CLI profiles
profiles=$(aws configure list-profiles)

for profile in $profiles; do
  echo "Checking profile: $profile"
  
  # Get all regions for this profile
  regions=$(aws ec2 describe-regions --profile "$profile" --query "Regions[*].RegionName" --output text)

  for region in $regions; do
    echo "  Region: $region"

    # Get instance details
    instances=$(aws ec2 describe-instances \
      --profile "$profile" \
      --region "$region" \
      --query "Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,Tags]" \
      --output json 2>/dev/null)

    # Parse each instance
    echo "$instances" | jq -c '.[][]' | while read -r instance; do
      instance_id=$(echo "$instance" | jq -r '.[0]')
      instance_type=$(echo "$instance" | jq -r '.[1]')
      state=$(echo "$instance" | jq -r '.[2]')
      tags=$(echo "$instance" | jq -c '.[3]')
      name=$(echo "$tags" | jq -r '.[]? | select(.Key == "Name") | .Value' 2>/dev/null)

      # Fallback if no Name tag
      name=${name:-""}

      # Write row to CSV
      echo "\"$profile\",\"$region\",\"$instance_id\",\"$instance_type\",\"$state\",\"$name\"" >> "$output_file"
    done
  done
done

echo "Report written to $output_file"

