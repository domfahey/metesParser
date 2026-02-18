import csv
import os
import subprocess


def get_accurate_page_count(filepath):
    """Get accurate page count using identify command"""
    try:
        # Use identify with proper format to get page count
        result = subprocess.run(
            ['identify', '-format', '%n\n', filepath],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            # Get the first line which contains the page count
            page_count = result.stdout.strip().split('\n')[0]
            return int(page_count)
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        pass
    return 1  # Default to 1 if we can't determine

def update_inventory_with_real_page_counts():
    """Update the inventory CSV with accurate page counts"""

    # Read existing inventory
    inventory = []
    with open('image_inventory.csv') as f:
        reader = csv.DictReader(f)
        inventory = list(reader)

    print(f"Updating page counts for {len(inventory)} files...")

    multi_page_files = []

    for i, row in enumerate(inventory):
        if i % 50 == 0:
            print(f"Processing {i}/{len(inventory)}...")

        filepath = os.path.join('images', row['filename'])
        real_page_count = get_accurate_page_count(filepath)

        row['page_count'] = str(real_page_count)

        if real_page_count > 1:
            multi_page_files.append((row['filename'], real_page_count))

    # Write updated inventory
    fieldnames = list(inventory[0].keys())
    with open('image_inventory_updated.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory)

    # Print summary
    print("\n" + "=" * 60)
    print(f"Total files: {len(inventory)}")
    print(f"Multi-page files: {len(multi_page_files)}")

    if multi_page_files:
        print("\nMulti-page TIF files found:")
        # Sort by page count
        multi_page_files.sort(key=lambda x: x[1], reverse=True)
        for filename, pages in multi_page_files[:20]:  # Show top 20
            print(f"  {filename}: {pages} pages")

        if len(multi_page_files) > 20:
            print(f"  ... and {len(multi_page_files) - 20} more files")

        # Statistics
        page_counts = [p for _, p in multi_page_files]
        print("\nPage count statistics for multi-page files:")
        print(f"  Maximum pages: {max(page_counts)}")
        print(f"  Minimum pages: {min(page_counts)}")
        print(f"  Average pages: {sum(page_counts) / len(page_counts):.1f}")

        # Total pages
        total_pages = sum(int(row['page_count']) for row in inventory)
        print(f"\nTotal pages across all files: {total_pages}")

if __name__ == "__main__":
    update_inventory_with_real_page_counts()
