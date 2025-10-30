import boto3
import sys

def clear_bucket_versions(bucket_name: str, region: str):
    """
    Deletes all object versions and delete markers from a versioned S3 bucket.
    """
    print(f"Connecting to S3 in region: {region}...")
    s3 = boto3.resource('s3', region_name=region)
    bucket = s3.Bucket(bucket_name)
    
    print(f"Clearing all versions from bucket: {bucket_name}")

    try:
        # Delete all object versions
        print("Deleting object versions...")
        bucket.object_versions.delete()

        print(f"Successfully cleared all versions from bucket '{bucket_name}'.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please check your AWS credentials and permissions.")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python clear_bucket.py <bucket-name>")
        sys.exit(1)
        
    BUCKET_TO_CLEAR = sys.argv[1]
    AWS_REGION = "ap-northeast-2"  # Specify your region
    
    clear_bucket_versions(BUCKET_TO_CLEAR, AWS_REGION)