import csv
import hashlib
import os
from datetime import datetime


def get_file_sha256(filepath):
    """Calculate SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def get_tif_page_count(filepath):
    """Get number of pages in a TIF file"""
    # For now, return 1 as we don't have PIL installed
    # TIF files in this dataset appear to be single-page documents
    return 1

def create_image_inventory(image_dir):
    """Create inventory of all images with metadata"""
    inventory = []

    # Get all TIF files
    tif_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.TIF')])

    print(f"Processing {len(tif_files)} TIF files...")

    for i, filename in enumerate(tif_files, 1):
        filepath = os.path.join(image_dir, filename)

        # Get file stats
        file_stats = os.stat(filepath)
        file_size = file_stats.st_size

        # Get file modification time
        mod_time = datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        # Extract book and page from filename
        # Format: MIWAYN-50004-01415.TIF
        parts = filename.replace('.TIF', '').split('-')
        if len(parts) == 3:
            book_number = parts[1]
            page_number = parts[2]
        else:
            book_number = ""
            page_number = ""

        # Get page count
        page_count = get_tif_page_count(filepath)

        # Calculate SHA-256
        print(f"Processing {i}/{len(tif_files)}: {filename}")
        sha256 = get_file_sha256(filepath)

        # Add to inventory
        inventory.append({
            'filename': filename,
            'book_number': book_number,
            'page_number': page_number,
            'file_size_bytes': file_size,
            'file_size_mb': round(file_size / (1024 * 1024), 2),
            'page_count': page_count,
            'sha256': sha256,
            'modification_time': mod_time,
            'has_ground_truth': os.path.exists(
                os.path.join(image_dir, '..', 'gt', f'{filename}.json')
            )
        })

    return inventory

def write_inventory_csv(inventory, output_file):
    """Write inventory to CSV file"""
    fieldnames = [
        'filename',
        'book_number',
        'page_number',
        'file_size_bytes',
        'file_size_mb',
        'page_count',
        'sha256',
        'modification_time',
        'has_ground_truth'
    ]

    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory)

def generate_summary_stats(inventory):
    """Generate summary statistics"""
    total_files = len(inventory)
    total_size_bytes = sum(item['file_size_bytes'] for item in inventory)
    total_size_gb = round(total_size_bytes / (1024 * 1024 * 1024), 2)
    total_pages = sum(item['page_count'] for item in inventory)
    files_with_gt = sum(1 for item in inventory if item['has_ground_truth'])

    avg_file_size_mb = round(sum(item['file_size_mb'] for item in inventory) / total_files, 2)

    # Count unique books
    unique_books = len({item['book_number'] for item in inventory if item['book_number']})

    print("\n=== Image Inventory Summary ===")
    print(f"Total TIF files: {total_files}")
    print(f"Total size: {total_size_gb} GB")
    print(f"Average file size: {avg_file_size_mb} MB")
    print(f"Total pages across all files: {total_pages}")
    gt_pct = round(files_with_gt / total_files * 100, 1)
    print(f"Files with ground truth JSON: {files_with_gt} ({gt_pct}%)")
    print(f"Unique books: {unique_books}")
    min_book = min(item['book_number'] for item in inventory)
    max_book = max(item['book_number'] for item in inventory)
    print(f"Book range: {min_book} - {max_book}")

def main():
    image_dir = 'images'
    output_csv = 'image_inventory.csv'

    print("Creating image inventory...")
    inventory = create_image_inventory(image_dir)

    print(f"\nWriting inventory to {output_csv}...")
    write_inventory_csv(inventory, output_csv)

    generate_summary_stats(inventory)

    print(f"\nInventory saved to {output_csv}")

if __name__ == "__main__":
    main()
