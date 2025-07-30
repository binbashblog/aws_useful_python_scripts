#!/bin/bash

# Define output CSV and Excel file names
csv_file="aws_public_ips.csv"
excel_file="aws_public_ips.xlsx"

# Get all AWS regions
regions=$(aws ec2 describe-regions --query "Regions[].RegionName" --output text)

# Get all profiles from the .aws/config file (including default)
profiles=$(awk -F'[][]' '/^\[profile/ {print $2}' ~/.aws/config | sed 's/^profile //' )

# Add the default profile explicitly if it exists
profiles="default $profiles"

# Create CSV header
echo "Account ID,Profile,Region,Instance ID,Public IP,Instance Name" > "$csv_file"

echo "Fetching instances with public IPs..."

# Loop through all profiles
all_data=""

for profile in $profiles; do
    echo "Using AWS profile: $profile"

    # Get AWS Account ID
    account_id=$(aws sts get-caller-identity --profile "$profile" --query "Account" --output text)

    # Store the data for each profile to be written to Excel later
    profile_data=""

    for region in $regions; do
        echo "Checking region: $region"

        # Fetch instances with a public IP and their tags
        instances=$(aws ec2 describe-instances --region "$region" --profile "$profile" \
            --query "Reservations[].Instances[?PublicIpAddress!=null].[InstanceId, PublicIpAddress, Tags[?Key=='Name'].Value | [0]]" \
            --output text)
        
        # Append results to the profile's data if instances exist
        if [[ -n "$instances" ]]; then
            while read -r instance_id public_ip instance_name; do
                profile_data="$profile_data$account_id,$profile,$region,$instance_id,$public_ip,$instance_name\n"
                all_data="$all_data$account_id,$profile,$region,$instance_id,$public_ip,$instance_name\n"
            done <<< "$instances"
        fi
    done

    # Append the profile data to the CSV file
    echo -e "$profile_data" >> "$csv_file"
done

echo "CSV file created: $csv_file"

# Convert CSV to Excel using Python (pandas)
python3 - <<EOF
import pandas as pd
import openpyxl
from openpyxl.styles import Alignment

# Load CSV into a DataFrame
df = pd.read_csv("$csv_file", dtype=str)  # Treat all columns as text

# Create an Excel writer
with pd.ExcelWriter("$excel_file") as writer:
    # Group the DataFrame by Profile and write each group to a different sheet
    for profile, group in df.groupby('Profile'):
        group.to_excel(writer, sheet_name=profile, index=False)

    # Write all profiles into a single sheet called 'All_Profiles'
    df.to_excel(writer, sheet_name='All_Profiles', index=False)

    # Get the workbook and set the text wrapping for all sheets
    workbook = writer.book
    for sheetname in workbook.sheetnames:
        worksheet = workbook[sheetname]
        for row in worksheet.iter_rows():
            for cell in row:
                # Set text wrapping and ensure cells are treated as text
                cell.alignment = Alignment(wrap_text=True)
                cell.number_format = '@'  # Force cell to be text

        # Adjust column widths based on the maximum content length in each column
        for col in worksheet.columns:
            max_length = 0
            column = [cell for cell in col]
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2)  # Adding extra padding for readability
            worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

print("Excel file created:", "$excel_file")
EOF

echo "Excel file saved as: $excel_file"

